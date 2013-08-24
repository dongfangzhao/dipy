"""
Cross-validation analysis of diffusion models




"""
from __future__ import division, print_function, absolute_import
from dipy.utils.six.moves import range

import numpy as np
import dipy.core.gradients as gt

def kfold_xval(model, data, folds):
    """
    Given a Model object perform iterative k-fold cross-validation of fitting
    that model

    Parameters
    ----------
    model : class instance of a Model

    data : ndarray
        Diffusion MRI data acquired with the gtab of the model

    folds: int
        The number of divisions to apply to the data

    Notes
    -----
    This function assumes that a prediction API is implemented in the Model
    class for which prediction is conducted. That is, the Fit object that gets
    generated upon fitting the model needs to have a `predict` method, which
    receives a GradientTable class instance as input and produces a predicted
    signal as output.

    It also assumes that the model object has `bval` and `bvec` attributes
    holding b-values and corresponding unit vectors.

    """
    gtab = gt.gradient_table(model.bval, model.bvec)
    data_d = data[..., ~gtab.b0s_mask]
    modder =  np.mod(data_d.shape[-1], folds)
    # Make sure that an equal number of samples get left out in each fold:
    if modder!= 0:
        msg = "The number of folds must divide the diffusion-weighted "
        msg += "data equally, but "
        msg = "np.mod(%s, %s) is %s"%(data_d.shape[-1], folds, modder)
        raise ValueError(msg)

    data_0 = data[..., gtab.b0s_mask]
    S0 = np.mean(data_0, -1)
    n_in_fold = data_d.shape[-1]/folds
    # We are going to leave out some randomly chosen samples in each iteration:
    order = np.random.permutation(data_d.shape[-1])
    prediction = np.zeros(data_d.shape)

    nz_bval = gtab.bvals[~gtab.b0s_mask]
    nz_bvec = gtab.bvecs[~gtab.b0s_mask]
    for k in range(folds):
        fold_mask = np.ones(data_d.shape[-1], dtype=bool)
        fold_idx = order[k*n_in_fold:(k+1)*n_in_fold]
        fold_mask[fold_idx] = False
        this_data = np.concatenate([data_0, data_d[..., fold_mask]], -1)

        this_gtab = gt.gradient_table(np.hstack([model.bval[gtab.b0s_mask],
                                                 nz_bval[fold_mask]]),
                                      np.concatenate([model.bvec[gtab.b0s_mask],
                                                 nz_bvec[fold_mask]]))
        left_out_gtab = gt.gradient_table(np.hstack([model.bval[gtab.b0s_mask],
                                                 nz_bval[~fold_mask]]),
                                      np.concatenate([model.bvec[gtab.b0s_mask],
                                                 nz_bvec[~fold_mask]]))

        this_model = model.__class__(this_gtab)
        this_fit = this_model.fit(this_data)
        this_predict = this_fit.predict(left_out_gtab, S0=S0)
        prediction[..., ~fold_mask] = this_predict[..., np.sum(gtab.b0s_mask):]

    return prediction
