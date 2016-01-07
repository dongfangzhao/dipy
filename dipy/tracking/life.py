"""
Linear Fascicle Evaluation : LiFE.

This is an implementation of the Linear Fascicle Evaluation (LiFE) algorithm
described in:

Pestilli, F., Yeatman, J, Rokem, A. Kay, K. and Wandell B.A. (2014). Validation
and statistical inference in living connectomes. Nature Methods 11:
1058-1063. doi:10.1038/nmeth.3098
"""
import numpy as np
import scipy.sparse as sps
import scipy.linalg as la

from dipy.reconst.base import ReconstModel, ReconstFit
from dipy.utils.six.moves import range
from dipy.tracking.utils import unique_rows
from dipy.tracking.streamline import transform_streamlines
import dipy.data as dpd
from dipy.tracking.vox2track import streamline_mapping, _voxel2streamline
from dipy.tracking.spdot import spdot, spdot_t, gradient_change
import dipy.core.optimize as opt


def gradient(f):
    """
    Return the gradient of an N-dimensional array.

    The gradient is computed using central differences in the interior
    and first differences at the boundaries. The returned gradient hence has
    the same shape as the input array.

    Parameters
    ----------
    f : array_like
      An N-dimensional array containing samples of a scalar function.

    Returns
    -------
    gradient : ndarray
      N arrays of the same shape as `f` giving the derivative of `f` with
      respect to each dimension.

    Examples
    --------
    >>> x = np.array([1, 2, 4, 7, 11, 16], dtype=np.float)
    >>> gradient(x)
    array([ 1. ,  1.5,  2.5,  3.5,  4.5,  5. ])

    >>> gradient(np.array([[1, 2, 6], [3, 4, 5]], dtype=np.float))
    [array([[ 2.,  2., -1.],
           [ 2.,  2., -1.]]), array([[ 1. ,  2.5,  4. ],
           [ 1. ,  1. ,  1. ]])]

    Note
    ----
    This is a simplified implementation of gradient that is part of numpy
    1.8. In order to mitigate the effects of changes added to this
    implementation in version 1.9 of numpy, we include this implementation
    here.
    """
    f = np.asanyarray(f)
    N = len(f.shape)  # number of dimensions
    dx = [1.0]*N

    # use central differences on interior and first differences on endpoints
    outvals = []

    # create slice objects --- initially all are [:, :, ..., :]
    slice1 = [slice(None)]*N
    slice2 = [slice(None)]*N
    slice3 = [slice(None)]*N

    for axis in range(N):
        # select out appropriate parts for this dimension
        out = np.empty_like(f)
        slice1[axis] = slice(1, -1)
        slice2[axis] = slice(2, None)
        slice3[axis] = slice(None, -2)
        # 1D equivalent -- out[1:-1] = (f[2:] - f[:-2])/2.0
        out[slice1] = (f[slice2] - f[slice3])/2.0
        slice1[axis] = 0
        slice2[axis] = 1
        slice3[axis] = 0
        # 1D equivalent -- out[0] = (f[1] - f[0])
        out[slice1] = (f[slice2] - f[slice3])
        slice1[axis] = -1
        slice2[axis] = -1
        slice3[axis] = -2
        # 1D equivalent -- out[-1] = (f[-1] - f[-2])
        out[slice1] = (f[slice2] - f[slice3])

        # divide by step size
        outvals.append(out / dx[axis])
        # reset the slice object in this dimension to ":"
        slice1[axis] = slice(None)
        slice2[axis] = slice(None)
        slice3[axis] = slice(None)

    if N == 1:
        return outvals[0]
    else:
        return outvals


def streamline_gradients(streamline):
    """
    Calculate the gradients of the streamline along the spatial dimension

    Parameters
    ----------
    streamline : array-like of shape (n, 3)
        The 3d coordinates of a single streamline

    Returns
    -------
    Array of shape (3, n): Spatial gradients along the length of the
    streamline.

    """
    return np.array(gradient(np.asarray(streamline))[0])


def grad_tensor(grad, evals):
    """
    Calculate the 3 by 3 tensor for a given spatial gradient, given a canonical
    tensor shape (also as a 3 by 3), pointing at [1,0,0]

    Parameters
    ----------
    grad : 1d array of shape (3,)
        The spatial gradient (e.g between two nodes of a streamline).

    evals: 1d array of shape (3,)
        The eigenvalues of a canonical tensor to be used as a response
        function.

    """
    # This is the rotation matrix from [1, 0, 0] to this gradient of the sl:
    R = la.svd(np.matrix(grad), overwrite_a=True)[2]
    # This is the 3 by 3 tensor after rotation:
    T = np.dot(np.dot(R, np.diag(evals)), R.T)
    return T


def streamline_tensors(streamline, evals=[0.001, 0, 0]):
    """
    The tensors generated by this fiber.

    Parameters
    ----------
    streamline : array-like of shape (n, 3)
        The 3d coordinates of a single streamline

    evals : iterable with three entries
        The estimated eigenvalues of a single fiber tensor.
        (default: [0.001, 0, 0]).

    Returns
    -------
    An n_nodes by 3 by 3 array with the tensor for each node in the fiber.

    Note
    ----
    Estimates of the radial/axial diffusivities may rely on
    empirical measurements (for example, the AD in the Corpus Callosum), or
    may be based on a biophysical model of some kind.
    """

    grad = streamline_gradients(streamline)

    # Preallocate:
    tensors = np.empty((grad.shape[0], 3, 3))

    for grad_idx, this_grad in enumerate(grad):
        tensors[grad_idx] = grad_tensor(this_grad, evals)
    return tensors


def streamline_signal(streamline, gtab, evals=[0.001, 0, 0]):
    """
    The signal from a single streamline estimate along each of its nodes.

    Parameters
    ----------
    streamline : a single streamline

    gtab : GradientTable class instance

    evals : list of length 3 (optional. Default: [0.001, 0, 0])
        The eigenvalues of the canonical tensor used as an estimate of the
        signal generated by each node of the streamline.
    """
    # Gotta have those tensors:
    tensors = streamline_tensors(streamline, evals)
    sig = np.empty((len(streamline), np.sum(~gtab.b0s_mask)))
    # Extract them once:
    bvecs = gtab.bvecs[~gtab.b0s_mask]
    bvals = gtab.bvals[~gtab.b0s_mask]
    for ii, tensor in enumerate(tensors):
        ADC = np.diag(np.dot(np.dot(bvecs, tensor), bvecs.T))
        # Use the Stejskal-Tanner equation with the ADC as input, and S0 = 1:
        sig[ii] = np.exp(-bvals * ADC)
    return sig - np.mean(sig)


class LifeSignalMaker(object):
    """
    A class for generating signals from streamlines in an efficient and speedy
    manner.
    """
    def __init__(self, gtab, evals=[0.001, 0, 0], sphere=None):
        """
        Initialize a signal maker

        Parameters
        ----------
        gtab : GradientTable class instance
            The gradient table on which the signal is calculated.
        evals : list of 3 items
            The eigenvalues of the canonical tensor to use in calculating the
            signal.
        n_points : `dipy.core.Sphere` class instance
            The discrete sphere to use as an approximation for the continuous
            sphere on which the signal is represented. If integer - we will use
            an instance of one of the symmetric spheres cached in
            `dps.get_sphere`. If a 'dipy.core.Sphere' class instance is
            provided, we will use this object. Default: the :mod:`dipy.data`
            symmetric sphere with 724 vertices
        """
        if sphere is None:
            self.sphere = dpd.get_sphere('symmetric724')
        else:
            self.sphere = sphere

        self.gtab = gtab
        self.evals = evals
        # Initialize an empty dict to fill with signals for each of the sphere
        # vertices:
        self.signal = np.empty((self.sphere.vertices.shape[0],
                                np.sum(~gtab.b0s_mask)))
        # We'll need to keep track of what we've already calculated:
        self._calculated = []

    def calc_signal(self, xyz):
        idx = self.sphere.find_closest(xyz)
        if idx not in self._calculated:
            bvecs = self.gtab.bvecs[~self.gtab.b0s_mask]
            bvals = self.gtab.bvals[~self.gtab.b0s_mask]
            tensor = grad_tensor(self.sphere.vertices[idx], self.evals)
            ADC = np.diag(np.dot(np.dot(bvecs, tensor), bvecs.T))
            sig = np.exp(-bvals * ADC)
            sig = sig - np.mean(sig)
            self.signal[idx] = sig
            self._calculated.append(idx)

        return self.signal[idx]

    def streamline_signal(self, streamline):
        """
        Approximate the signal for a given streamline
        """
        grad = streamline_gradients(streamline)
        sig_out = np.zeros((grad.shape[0], self.signal.shape[-1]))
        for ii, g in enumerate(grad):
            sig_out[ii] = self.calc_signal(g)
        return sig_out


def voxel2streamline(streamline, transformed=False, affine=None,
                     unique_idx=None):
    """
    Maps voxels to streamlines and streamlines to voxels, for setting up
    the LiFE equations matrix

    Parameters
    ----------
    streamline : list
        A collection of streamlines, each n by 3, with n being the number of
        nodes in the fiber.

    affine : 4 by 4 array (optional)
       Defines the spatial transformation from streamline to data.
       Default: np.eye(4)

    transformed : bool (optional)
        Whether the streamlines have been already transformed (in which case
        they don't need to be transformed in here).

    unique_idx : array (optional).
       The unique indices in the streamlines

    Returns
    -------
    v2f, v2fn : tuple of dicts

    The first dict in the tuple answers the question: Given a voxel (from
    the unique indices in this model), which fibers pass through it?

    The second answers the question: Given a streamline, for each voxel that
    this streamline passes through, which nodes of that streamline are in that
    voxel?
    """
    if transformed:
        transformed_streamline = streamline
    else:
        if affine is None:
            affine = np.eye(4)
        transformed_streamline = transform_streamlines(streamline, affine)

    if unique_idx is None:
        all_coords = np.concatenate(transformed_streamline)
        unique_idx = unique_rows(np.round(all_coords))

    return _voxel2streamline(transformed_streamline,
                             unique_idx.astype(np.intp))



class FiberModel(ReconstModel):
    """Representing and solving models based on tractography solutions.

    Notes
    -----
    This is an implementation of the LiFE model described in [1]_.

    [1] Pestilli, F., Yeatman, J, Rokem, A. Kay, K. and Wandell
        B.A. (2014). Validation and statistical inference in living
        connectomes. Nature Methods.
    """
    def __init__(self, gtab, conserve_memory=False):
        """
        Parameters
        ----------
        gtab : GradientTable
        conserve_memory : bool
            Whether to use a memory-efficient version of fitting. This version
            of fitting performs out-of-core fitting, instead of representing
            the model explicitely. Therefore, this model will not have a
            life_matrix attribute.
        """
        # Initialize the super-class:
        ReconstModel.__init__(self, gtab)
        if conserve_memory:
            self.fit = self._fit_memory
        else:
            self.fit = self._fit_speed

    def _signal_maker(self, evals=[0.001, 0, 0], sphere=None):
        """Make the signal portion of the LiFE matrix.

        Parameters
        ----------
        gtab : GradientTable
            The gradient table on which the signal is calculated.
        evals : list of 3 items
            The eigenvalues of the canonical tensor to use in calculating the
            signal.
        """
        if sphere is None:
            sphere = dpd.get_sphere()

        bvecs = self.gtab.bvecs[~self.gtab.b0s_mask]
        bvals = self.gtab.bvals[~self.gtab.b0s_mask]
        # This will be the output
        signal = np.empty((sphere.vertices.shape[0], bvals.shape[0]))

        # Calculate for every direction on the sphere:
        for idx in range(sphere.vertices.shape[0]):
            tensor = grad_tensor(sphere.vertices[idx], evals)
            ADC = np.diag(np.dot(np.dot(bvecs, tensor), bvecs.T))
            sig = np.exp(-bvals * ADC)
            sig = sig - np.mean(sig)
            signal[idx] = sig

        return signal

    def _fit_signals(self, data, vox_coords):
        """
        Helper function to extract and separate all the signals we need to fit
        and evaluate a fit of this model

        Parameters
        ----------
        data : 4D array

        vox_coords: n by 3 array
            The coordinates into the data array of the fiber nodes.
        """
        # Fitting is done on the S0-normalized-and-demeaned diffusion-weighted
        # signal:
        idx_tuple = (vox_coords[:, 0], vox_coords[:, 1], vox_coords[:, 2])
        # We'll look at a 2D array, extracting the data from the voxels:
        vox_data = data[idx_tuple]
        weighted_signal = vox_data[:, ~self.gtab.b0s_mask]
        b0_signal = np.mean(vox_data[:, self.gtab.b0s_mask], -1)
        relative_signal = (weighted_signal/b0_signal[:, None])

        # The mean of the relative signal across directions in each voxel:
        mean_sig = np.mean(relative_signal, -1)
        to_fit = (relative_signal - mean_sig[:, None]).ravel()
        return (to_fit, weighted_signal, b0_signal, relative_signal, mean_sig,
                vox_data)


    def setup(self, streamline, affine, evals=[0.001, 0, 0], sphere=None):
        """
        Set up the necessary components for the LiFE model: the matrix of
        fiber-contributions to the DWI signal, and the coordinates of voxels
        for which the equations will be solved
        Parameters
        ----------
        streamline : list
            Streamlines, each is an array of shape (n, 3)
        affine : 4 by 4 array
            Mapping from the streamline coordinates to the data
        evals : list (3 items, optional)
            The eigenvalues of the canonical tensor used as a response
            function. Default:[0.001, 0, 0].
        sphere: `dipy.core.Sphere` instance.
            Whether to approximate (and cache) the signal on a discrete
            sphere. This may confer a significant speed-up in setting up the
            problem, but is not as accurate. If `False`, we use the exact
            gradients along the streamlines to calculate the matrix, instead of
            an approximation. Defaults to use the 724-vertex symmetric sphere
            from :mod:`dipy.data`
        """
        if sphere is not False:
            SignalMaker = LifeSignalMaker(self.gtab,
                                          evals=evals,
                                          sphere=sphere)

        if affine is None:
            affine = np.eye(4)
        streamline = transform_streamlines(streamline, affine)
        # Assign some local variables, for shorthand:
        all_coords = np.concatenate(streamline)
        vox_coords = unique_rows(np.round(all_coords).astype(np.intp))
        del all_coords
        # We only consider the diffusion-weighted signals:
        n_bvecs = self.gtab.bvals[~self.gtab.b0s_mask].shape[0]
        v2f, v2fn = voxel2streamline(streamline, transformed=True,
                                     affine=affine, unique_idx=vox_coords)
        # How many fibers in each voxel (this will determine how many
        # components are in the matrix):
        n_unique_f = len(np.hstack(v2f.values()))
        # Preallocate these, which will be used to generate the sparse
        # matrix:
        f_matrix_sig = np.zeros(n_unique_f * n_bvecs, dtype=np.float)
        f_matrix_row = np.zeros(n_unique_f * n_bvecs, dtype=np.intp)
        f_matrix_col = np.zeros(n_unique_f * n_bvecs, dtype=np.intp)

        fiber_signal = []
        for s_idx, s in enumerate(streamline):
            if sphere is not False:
                fiber_signal.append(SignalMaker.streamline_signal(s))
            else:
                fiber_signal.append(streamline_signal(s, self.gtab, evals))

        del streamline
        if sphere is not False:
            del SignalMaker

        keep_ct = 0
        range_bvecs = np.arange(n_bvecs).astype(int)
        # In each voxel:
        for v_idx in range(vox_coords.shape[0]):
            mat_row_idx = (range_bvecs + v_idx * n_bvecs).astype(np.intp)
            # For each fiber in that voxel:
            for f_idx in v2f[v_idx]:
                # For each fiber-voxel combination, store the row/column
                # indices in the pre-allocated linear arrays
                f_matrix_row[keep_ct:keep_ct+n_bvecs] = mat_row_idx
                f_matrix_col[keep_ct:keep_ct+n_bvecs] = f_idx

                vox_fiber_sig = np.zeros(n_bvecs)
                for node_idx in v2fn[f_idx][v_idx]:
                    # Sum the signal from each node of the fiber in that voxel:
                    vox_fiber_sig += fiber_signal[f_idx][node_idx]
                # And add the summed thing into the corresponding rows:
                f_matrix_sig[keep_ct:keep_ct+n_bvecs] += vox_fiber_sig
                keep_ct = keep_ct + n_bvecs

        del v2f, v2fn
        # Allocate the sparse matrix, using the more memory-efficient 'csr'
        # format:
        life_matrix = sps.csr_matrix((f_matrix_sig,
                                     [f_matrix_row, f_matrix_col]))

        return life_matrix, vox_coords


    def _fit_speed(self, data, streamline, affine=None, evals=[0.001, 0, 0],
                   sphere=None):
        """
        Fit the LiFE FiberModel for data and a set of streamlines associated
        with this data
        Parameters
        ----------
        data : 4D array
           Diffusion-weighted data
        streamline : list
           A bunch of streamlines
        affine: 4 by 4 array (optional)
           The affine to go from the streamline coordinates to the data
           coordinates. Defaults to use `np.eye(4)`
        evals : list (optional)
           The eigenvalues of the tensor response function used in constructing
           the model signal. Default: [0.001, 0, 0]
        sphere: `dipy.core.Sphere` instance, or False
            Whether to approximate (and cache) the signal on a discrete
            sphere. This may confer a significant speed-up in setting up the
            problem, but is not as accurate. If `False`, we use the exact
            gradients along the streamlines to calculate the matrix, instead of
            an approximation.
        Returns
        -------
        FiberFit class instance
        """
        if affine is None:
            affine = np.eye(4)
        life_matrix, vox_coords = \
            self.setup(streamline, affine, evals=evals, sphere=sphere)
        (to_fit, weighted_signal, b0_signal, relative_signal, mean_sig,
         vox_data) = self._fit_signals(data, vox_coords)
        beta = opt.sparse_nnls(to_fit, life_matrix)
        return FiberFitSpeed(self, life_matrix, vox_coords, to_fit, beta,
                             weighted_signal, b0_signal, relative_signal,
                             mean_sig, vox_data, streamline, affine, evals)

    def _fit_memory(self, data, streamline, affine=None, evals=[0.001, 0, 0],
                    sphere=None, check_error_iter=5, converge_on_sse=0.8,
                    max_error_checks=5, step_size=0.01):
        """
        Fit the LiFE model.

        Parameters
        ----------
        data : ndarray
        streamline : list
            Streamlines, each is an array of shape (n, 3)
        affine : 4 by 4 array
            Mapping from the streamline coordinates to the data
        evals : list (3 items, optional)
            The eigenvalues of the canonical tensor used as a response
            function. Default:[0.001, 0, 0].
        sphere: `dipy.core.Sphere` instance.
            Whether to approximate (and cache) the signal on a discrete
            sphere. This may confer a significant speed-up in setting up the
            problem, but is not as accurate. If `False`, we use the exact
            gradients along the streamlines to calculate the matrix, instead of
            an approximation. Defaults to use the :mod:`dipy.data`
            `default_sphere`.
        check_error_iter : int
            In optimization, how many iterations to perform between checks for
            convergence.
        converge_on_sse : float
            In optimization, the desired rate of convergence. The new sum of
            squared errors is required to be convergence_on_see * the previous
            sum of squared errors, for optimization to continue.
        max_error_checks : int
            How many rounds of optimization to perform at most, after reaching
            convergence.
        step_size : float
            In optimization, the size of the gradient step change to the
            parameters to perform in each round.
        """
        if sphere is None:
            sphere = dpd.get_sphere()

        signal_maker = self._signal_maker(evals=evals,
                                          sphere=sphere)

        if affine is None:
            affine = np.eye(4)
        else:
            streamline = transform_streamlines(streamline, affine)

        sl_as_coords = [np.round(s).astype(np.intp) for s in streamline]
        cat_streamline = np.concatenate(sl_as_coords)
        vox_coords = unique_rows(cat_streamline)
        v2f = streamline_mapping(sl_as_coords, affine=np.eye(4))

        (to_fit, weighted_signal, b0_signal, relative_signal, mean_sig,
         vox_data) = self._fit_signals(data, vox_coords)
        del weighted_signal, b0_signal, relative_signal, mean_sig
        closest = {}
        for sl_idx, ss in enumerate(streamline):
            closest[sl_idx] = []
            for node_idx in range(ss.shape[0]):
                if node_idx == 0:
                    g = ss[1] - ss[0]
                elif node_idx == ss.shape[0]:
                    g = ss[-1] - ss[-2]
                else:
                    g = ss[node_idx] - ss[node_idx-1]
                closest[sl_idx].append(sphere.find_closest(g))
        # We only consider the diffusion-weighted signals in fitting:
        n_bvecs = self.gtab.bvals[~self.gtab.b0s_mask].shape[0]
        beta = np.zeros(len(streamline))
        range_bvecs = np.arange(n_bvecs).astype(np.intp)

        # Optimization-related stuff:
        iteration = 0
        ss_residuals_min = np.inf
        sse_best = np.inf
        error_checks = 0  # How many error checks have we done so far
        y_hat = np.zeros(to_fit.shape)

        # Cache some facts about relationship between voxels and fibers:
        max_s_per_vox = np.max([len(t) for t in v2f.values()])
        s_in_vox = {}
        for v_idx in range(vox_coords.shape[0]):
            s_in_vox[v_idx] = []
            mat_row_idx = (range_bvecs + v_idx * n_bvecs).astype(np.intp)
            this_vox = (vox_coords[v_idx][0], vox_coords[v_idx][1],
                        vox_coords[v_idx][2])
            # For each fiber in that voxel:
            for sl_idx in v2f[this_vox]:
                find_vox = np.logical_and(
                  np.logical_and(
                    sl_as_coords[sl_idx][:, 0] == vox_coords[v_idx][0],
                    sl_as_coords[sl_idx][:, 1] == vox_coords[v_idx][1]),
                  sl_as_coords[sl_idx][:, 2] == vox_coords[v_idx][2])
                nodes_in_vox = np.where(find_vox)[0]
                s_in_vox[v_idx].append((sl_idx, nodes_in_vox))

        # We no longer need these variables:
        del v2f, streamline, sl_as_coords

        delta = np.zeros(beta.shape)
        while 1:
            for v_idx in range(vox_coords.shape[0]):
                mat_row_idx = range_bvecs + v_idx * n_bvecs
                f_matrix_row = np.zeros(len(s_in_vox[v_idx] * n_bvecs),
                                        dtype=np.intp)
                f_matrix_col = np.zeros(len(s_in_vox[v_idx] * n_bvecs),
                                        dtype=np.intp)
                f_matrix_sig = np.zeros(len(s_in_vox[v_idx] * n_bvecs),
                                        dtype=float)
                for ii, (sl_idx, nodes_in_vox) in enumerate(s_in_vox[v_idx]):
                    f_matrix_row[ii*n_bvecs:ii*n_bvecs+n_bvecs] = range_bvecs
                    f_matrix_col[ii*n_bvecs:ii*n_bvecs+n_bvecs] = sl_idx
                    vox_fib_sig = np.zeros(n_bvecs)
                    for node_idx in nodes_in_vox:
                        signal_idx = closest[sl_idx][node_idx]
                        this_signal = signal_maker[signal_idx]
                        # Sum the signal from each node of the fiber in that
                        # voxel:
                        vox_fib_sig += this_signal
                    # And add the summed thing into the corresponding rows:
                    f_matrix_sig[ii*n_bvecs:ii*n_bvecs+n_bvecs] += vox_fib_sig

                if iteration == 0 or np.mod(iteration, check_error_iter):
                    # Calculate the gradient contribution from this voxel:
                    XtXby = gradient_change(f_matrix_row,
                                            f_matrix_col,
                                            f_matrix_sig,
                                            beta,
                                            to_fit[mat_row_idx],
                                            mat_row_idx.shape[0],
                                            delta.shape[0])
                    delta = delta + XtXby
                else:
                    # This time around, we're just calculating the current
                    # prediction for the signal:
                    y_hat[mat_row_idx] = spdot(f_matrix_row,
                                               f_matrix_col,
                                               f_matrix_sig,
                                               beta,
                                               f_matrix_row.shape[0],
                                               mat_row_idx.shape[0])

            if iteration == 0 or np.mod(iteration, check_error_iter):
                beta = beta - step_size * delta
                # Set negative values to 0 (non-negative!)
                beta[beta < 0] = 0
                delta[:] = 0
            else:
                print(iteration)
                sse = np.sum((to_fit - y_hat) ** 2)
                # Did we do better this time around?
                if sse < ss_residuals_min:
                    # Update your expectations about the minimum error:
                    ss_residuals_min = sse
                    beta_best = beta
                    # Are we generally (over iterations) converging?
                    if sse < sse_best * converge_on_sse:
                        sse_best = sse
                        count_bad = 0
                    else:
                        count_bad += 1
                else:
                    count_bad += 1
                if count_bad >= max_error_checks:
                    return FiberFitMemory(self,
                                          vox_coords,
                                          data,
                                          to_fit,
                                          beta_best,
                                          affine,
                                          evals,
                                          closest,
                                          s_in_vox)

                error_checks += 1
            iteration += 1

class FiberFitSpeed(ReconstFit):
    """
    A fit of the LiFE model to diffusion data
    """
    def __init__(self, fiber_model, life_matrix, vox_coords, to_fit, beta,
                 weighted_signal, b0_signal, relative_signal, mean_sig,
                 vox_data, streamline, affine, evals):
        """
        Parameters
        ----------
        fiber_model : A FiberModel class instance
        params : the parameters derived from a fit of the model to the data.
        """
        ReconstFit.__init__(self, fiber_model, vox_data)

        self.life_matrix = life_matrix
        self.vox_coords = vox_coords
        self.fit_data = to_fit
        self.beta = beta
        self.weighted_signal = weighted_signal
        self.b0_signal = b0_signal
        self.relative_signal = relative_signal
        self.mean_signal = mean_sig
        self.streamline = streamline
        self.affine = affine
        self.evals = evals

    def predict(self, gtab=None, S0=None):
        """
        Predict the signal
        Parameters
        ----------
        gtab : GradientTable
            Default: use self.gtab
        S0 : float or array
            The non-diffusion-weighted signal in the voxels for which a
            prediction is made. Default: use self.b0_signal
        Returns
        -------
        prediction : ndarray of shape (voxels, bvecs)
            An array with a prediction of the signal in each voxel/direction
        """
        # We generate the prediction and in each voxel, we add the
        # offset, according to the isotropic part of the signal, which was
        # removed prior to fitting:
        if gtab is None:
            _matrix = self.life_matrix
            gtab = self.model.gtab
        else:
            _model = FiberModel(gtab)
            _matrix, _ = _model.setup(self.streamline,
                                      self.affine,
                                      self.evals)

        pred_weighted = np.reshape(opt.spdot(_matrix, self.beta),
                                   (self.vox_coords.shape[0],
                                    np.sum(~gtab.b0s_mask)))

        pred = np.empty((self.vox_coords.shape[0], gtab.bvals.shape[0]))
        if S0 is None:
            S0 = self.b0_signal

        pred[..., gtab.b0s_mask] = S0[:, None]
        pred[..., ~gtab.b0s_mask] =\
            (pred_weighted + self.mean_signal[:, None]) * S0[:, None]

        return pred


class FiberFitMemory(ReconstFit):
    """
    A fit of the LiFE model to diffusion data
    """
    def __init__(self, fiber_model, vox_coords, data, to_fit, beta,
                 affine, evals, closest, s_in_vox):
        """
        Parameters
        ----------
        fiber_model : A FiberModel class instance

        params : the parameters derived from a fit of the model to the data.

        """
        (to_fit, weighted_signal, b0_signal, relative_signal, mean_sig,
         vox_data) = fiber_model._fit_signals(data, vox_coords)
        ReconstFit.__init__(self, fiber_model, vox_data)

        self.vox_coords = vox_coords
        self.fit_data = to_fit
        self.beta = beta
        self.weighted_signal = weighted_signal
        self.b0_signal = b0_signal
        self.relative_signal = relative_signal
        self.mean_signal = mean_sig
        self.affine = affine
        self.evals = evals
        self.closest = closest
        self.s_in_vox = s_in_vox

    def predict(self, streamline, gtab=None, S0=None, sphere=None):
        """
        Predict the signal

        Parameters
        ----------
        gtab : GradientTable
            Default: use self.gtab
        S0 : float or array
            The non-diffusion-weighted signal in the voxels for which a
            prediction is made. Default: use self.b0_signal

        Returns
        -------
        prediction : ndarray of shape (voxels, bvecs)
            An array with a prediction of the signal in each voxel/direction
        """
        # We generate the prediction and in each voxel, we add the
        # offset, according to the isotropic part of the signal, which was
        # removed prior to fitting:
        if gtab is None:
            gtab = self.model.gtab

        if sphere is None:
            sphere = dpd.get_sphere()

        signal_maker = self.model._signal_maker(evals=self.evals,
                                                sphere=sphere)

        n_bvecs = gtab.bvals[~gtab.b0s_mask].shape[0]
        f_matrix_shape = (self.fit_data.shape[0], len(streamline))
        range_bvecs = np.arange(n_bvecs).astype(int)
        pred_weighted = np.zeros(self.fit_data.shape)

        for v_idx in range(self.vox_coords.shape[0]):
                mat_row_idx = (range_bvecs + v_idx * n_bvecs).astype(np.intp)
                s_in_vox = self.s_in_vox[v_idx]
                f_matrix_row = np.zeros(len(s_in_vox) * n_bvecs, dtype=np.intp)
                f_matrix_col = np.zeros(len(s_in_vox) * n_bvecs, dtype=np.intp)
                f_matrix_sig = np.zeros(len(s_in_vox) * n_bvecs, dtype=float)
                for ii, (sl_idx, nodes_in_vox) in enumerate(s_in_vox):
                    ss = streamline[sl_idx]
                    f_matrix_row[ii*n_bvecs:ii*n_bvecs+n_bvecs] = range_bvecs
                    f_matrix_col[ii*n_bvecs:ii*n_bvecs+n_bvecs] = sl_idx
                    vox_fib_sig = np.zeros(n_bvecs)
                    for node_idx in nodes_in_vox:
                        signal_idx = self.closest[sl_idx][node_idx]
                        this_signal = signal_maker[signal_idx]
                        # Sum the signal from each node of the fiber in that
                        # voxel:
                        vox_fib_sig += this_signal
                    # And add the summed thing into the corresponding rows:
                    f_matrix_sig[ii*n_bvecs:ii*n_bvecs+n_bvecs] += vox_fib_sig

                pred_weighted[mat_row_idx] = spdot(f_matrix_row,
                                                   f_matrix_col,
                                                   f_matrix_sig,
                                                   self.beta,
                                                   f_matrix_row.shape[0],
                                                   mat_row_idx.shape[0])

        pred = np.empty((self.vox_coords.shape[0], gtab.bvals.shape[0]))
        pred[..., ~gtab.b0s_mask] = pred_weighted.reshape(
                                            pred[..., ~gtab.b0s_mask].shape)
        if S0 is None:
            S0 = self.b0_signal

        pred[..., gtab.b0s_mask] = S0[:, None]
        pred[..., ~gtab.b0s_mask] =\
            (pred[..., ~gtab.b0s_mask] +
             self.mean_signal[:, None]) * S0[:, None]

        return pred
