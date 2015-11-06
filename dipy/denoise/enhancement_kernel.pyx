import numpy as np
cimport numpy as cnp
cimport cython
import os.path

cimport safe_openmp as openmp
from safe_openmp cimport have_openmp
from cython.parallel import prange, threadid, parallel

from dipy.data import get_sphere
from dipy.core.sphere import disperse_charges, Sphere, HemiSphere
from tempfile import gettempdir
from libc.math cimport sqrt, exp, fabs, cos, sin, tan, acos, atan2
from math import ceil

cdef class EnhancementKernel:

    cdef double D33
    cdef double D44
    cdef double t
    cdef int kernelsize
    cdef double kernelmax
    cdef double [:, :] orientations
    cdef double [:, :, :, :, ::1] lookuptable
    cdef object sphere
    cdef object num_threads

    ## Python functions

    def __init__(self, D33, D44, t, force_recompute=False,
                    orientations=None, test_mode=False, num_threads=None):
        """ Compute a look-up table for the contextual
            enhancement kernel

        Parameters
        ----------
        D33 : float
            Spatial diffusion
        D44 : float
            Angular diffusion
        t   : float
            Diffusion time
        force_recompute : boolean
            Always compute the look-up table even if it is available
            in cache. Default is False.
        orientations : integer or Sphere object
            Specify the number of orientations to be used with
            electrostatic repulsion, or provide a Sphere object.
            The default sphere is 'repulsion100'.
        test_mode : boolean
            Computes the lookup-table in one direction only

        References
        -------
        [DuitsAndFranken2011] Duits, R. and Franken, E. (2011) Morphological and
                          Linear Scale Spaces for Fiber Enhancement in DWI-MRI.
                          J Math Imaging Vis, 46(3):326-368.
        [Portegies2015] J. Portegies, G. Sanguinetti, S. Meesters, and R. Duits. (2015)
                     New Approximation of a Scale Space Kernel on SE(3) and
                     Applications in Neuroimaging. Fifth International
                     Conference on Scale Space and Variational Methods in
                     Computer Vision
        [Portegies2015b] J. Portegies, R. Fick, G. Sanguinetti, S. Meesters, G.Girard,
                     and R. Duits. (2015) Improving Fiber Alignment in HARDI by
                     Combining Contextual PDE flow with Constrained Spherical
                     Deconvolution. PLoS One.
        """

        # save parameters as class members
        self.D33 = D33
        self.D44 = D44
        self.t = t

        # define a sphere
        if type(orientations) is Sphere:
            # use the sphere defined by the user
            sphere = orientations
        elif type(orientations) is int:
            # electrostatic repulsion based on number of orientations
            n_pts = orientations
            theta = np.pi * np.random.rand(n_pts)
            phi = 2 * np.pi * np.random.rand(n_pts)
            hsph_initial  = HemiSphere(theta=theta, phi=phi)
            sphere, potential = disperse_charges(hsph_initial , 5000)
        else:
            # use default
            sphere = get_sphere('repulsion100')
        self.orientations = sphere.vertices
        self.sphere = sphere

        # save openmp settings
        self.num_threads = num_threads

        # file location of the lut table for saving/loading
        kernellutpath = "%s/kernel_d33@%4.2f_d44@%4.2f_t@%4.2f_numverts%d.npy" \
                        % (gettempdir(), D33, D44, t, len(self.orientations))

        # create a lookup table in testing mode
        if test_mode:
            self.create_lookup_table(True)
            return

        # if LUT exists, load
        if not force_recompute and os.path.isfile(kernellutpath):
            print "The kernel already exists. Loading from " + kernellutpath
            self.lookuptable = np.load(kernellutpath)

        # else, create
        else:
            print "The kernel doesn't exist yet. Computing..."
            self.create_lookup_table()
            np.save(kernellutpath, self.lookuptable)

    def get_lookup_table(self):
        """ Return the computed look-up table.
        """
        return self.lookuptable

    def get_orientations(self):
        """ Return the orientations.
        """
        return self.orientations

    def get_sphere(self):
        """ Get the sphere corresponding with the orientations
        """
        return self.sphere

    def evaluate_kernel(self, x, y, r, v):
        return self.k2(x, y, r, v)

    # Cython functions

    @cython.wraparound(False)
    @cython.boundscheck(False)
    @cython.nonecheck(False)
    @cython.cdivision(True)
    cdef void create_lookup_table(self, test_mode = False):
        """ Compute the look-up table based on the parameters set
            during class initialization
        """
        self.estimate_kernel_size()

        cdef:
            double [:, :] orientations = np.copy(self.orientations)
            int OR1 = orientations.shape[0]
            int OR2 = orientations.shape[0]
            int N = self.kernelsize
            int hn = (N-1)/2
            cnp.npy_intp angv, angr, xp, yp, zp
            double [:] x
            double [:] y
            cdef double [:, :, :, :, ::1] lookuptablelocal
            double kmax = self.kernelmax
            double l1norm
            double kernelval

        # For testing, only compute one orientation of r
        if test_mode:
            OR2 = 1

        lookuptablelocal = np.zeros((OR1, OR2, N, N, N))
        x = np.zeros(3)
        y = np.zeros(3) # constant at (0,0,0)

        with nogil:
            for angv in range(OR1):
                for angr in range(OR2):
                    for xp in range(-hn, hn+1):
                        for yp in range(-hn, hn+1):
                            for zp in range(-hn, hn+1):

                                x[0] = xp
                                x[1] = yp
                                x[2] = zp

                                lookuptablelocal[angv,
                                                 angr,
                                                 xp+hn,
                                                 yp+hn,
                                                 zp+hn] = self.k2(x, y, orientations[angr,:], orientations[angv,:])

        # save to class member
        self.lookuptable = lookuptablelocal

    @cython.wraparound(False)
    @cython.boundscheck(False)
    @cython.nonecheck(False)
    @cython.cdivision(True)
    cdef void estimate_kernel_size(self):
        """ Estimates the dimensions the kernel should
            have based on the kernel parameters.
        """

        cdef:
            double [:] x
            double [:] y
            double [:] r
            double [:] v
            double i

        x = np.array([0., 0., 0.])
        y = np.array([0., 0., 0.])
        r = np.array([0., 0., 1.])
        v = np.array([0., 0., 1.])

        # evaluate at origin
        self.kernelmax = self.k2(x, y, r, v);

        with nogil:
            # determine a good kernel size
            i = 0.0
            while True:
                i += 0.1
                x[2] = i
                kval = self.k2(x, y, r, v)/self.kernelmax
                if(kval < 0.1):
                    break;

        N = ceil(i)*2
        if N%2 == 0:
            N -= 1

        #print("max kernel val: %f" % self.kernelmax);
        print("Dimensions of kernel: %dx%dx%d" % (N, N, N))

        self.kernelsize = N

    @cython.wraparound(False)
    @cython.boundscheck(False)
    @cython.nonecheck(False)
    cdef double k2(self, double [:] x, double [:] y,
                double [:] r, double [:] v) nogil:
        """ Evaluate the kernel at position x relative to
            position y, with orientation r relative to orientation v.
        """
        cdef:
            double [:] a
            double [:,:] transm
            double [:] arg1
            double [:] arg2p
            double [:] arg2
            double [:] c
            double kernelval

        with gil:
            a = np.subtract(x,y)
            transm = np.transpose(R(euler_angles(v)))
            arg1 = np.dot(transm,a)
            arg2p = np.dot(transm,r)
        arg2 = euler_angles(arg2p)

        c = self.coordinate_map(arg1[0], arg1[1], arg1[2],
                                arg2[0], arg2[1])
        kernelval = self.kernel(c)

        return kernelval

    @cython.wraparound(False)
    @cython.boundscheck(False)
    @cython.nonecheck(False)
    @cython.cdivision(True)
    cdef double [:] coordinate_map(self, double x, double y,
                                    double z, double beta,
                                    double gamma) nogil:
        """ Compute a coordinate map for the kernel

        Parameters
        ----------
        x : double
            X position
        y : double
            Y position
        z : double
            Z position
        beta : double
            First Euler angle
        gamma : double
            Second Euler angle

        Returns
        -------
        c : array of double
            array of coordinates for kernel
        """

        cdef:
            double [:] c
            double q
            double cg
            double cotq2
        with gil:
            c = np.zeros(6)
        if beta == 0:
            c[0] = x
            c[1] = y
            c[2] = z
            c[3] = c[4] = c[5] = 0

        else:
            q = fabs(beta)
            cg = cos(gamma)
            sg = sin(gamma)
            cotq2 = 1.0/tan(q/2)

            c[0] = -0.5*z*beta*cg + \
                    x*(1-(beta*beta*cg*cg*(1 - 0.5*q*cotq2))/(q*q)) - \
                     (y*beta*beta*cg*(1-0.5*q*cotq2)*sg)/(q*q)
            c[1] = -0.5*z*beta*sg - \
                    (x*beta*beta*cg*(1-0.5*q*cotq2)*sg)/(q*q) + \
                    y*(1-(beta*beta*(1-0.5*q*cotq2)*sg*sg)/(q*q))
            c[2] = 0.5*x*beta*cg + 0.5*y*beta*sg + \
                    z*(1+((1-0.5*q*cotq2)*(-beta*beta*cg*cg - \
                    beta*beta*sg*sg))/(q*q))
            c[3] = beta * (-sg)
            c[4] = beta * cg
            c[5] = 0

        with gil:
            return np.array(c)

    @cython.wraparound(False)
    @cython.boundscheck(False)
    @cython.nonecheck(False)
    @cython.cdivision(True)
    cdef double kernel(self, double [:] c) nogil:
        """ Evaluate the kernel based on the coordinate map.
        """
        return 1/(8*sqrt(2))*sqrt(PI)*self.t* \
                sqrt(self.t*self.D33)*sqrt(self.D33*self.D44) * \
                1/(16*PI*PI*self.D33*self.D33*self.D44*self.D44* \
                self.t*self.t*self.t*self.t) * \
                exp(-sqrt( (c[0]*c[0] + c[1]*c[1])/(self.D33*self.D44) \
                 + (c[2]*c[2]/self.D33 + \
                 (c[3]*c[3]+c[4]*c[4])/self.D44)*(c[2]*c[2]/self.D33 + \
                  (c[3]*c[3]+c[4]*c[4])/self.D44) + \
                  c[5]*c[5]/self.D44)/(4*self.t));


#### MATH FUNCTIONS ####

cdef double PI = 3.1415926535897932

# @cython.cdivision(True)
@cython.wraparound(False)
@cython.boundscheck(False)
cdef double [:] euler_angles(double [:] input) nogil:

    cdef:
        double x
        double y
        double z
        double [:] output

    x = input[0]
    y = input[1]
    z = input[2]
    with gil:
        output = np.zeros(3)

    # handle the case (0,0,1)
    if x*x < 10e-6 and y*y < 10e-6 and (z-1)*(z-1) < 10e-6:
        output[0] = 0
        output[1] = 0

    # handle the case (0,0,-1)
    elif x*x < 10e-6 and y*y < 10e-6 and (z+1)*(z+1) < 10e-6:
        output[0] = PI
        output[1] = 0

    # all other cases
    else:
        output[0] = acos(z)
        output[1] = atan2(y,x)

    with gil:

        return output

@cython.wraparound(False)
@cython.boundscheck(False)
cdef double [:,:] R(double [:] input) nogil:

    cdef:
        double beta
        double gamma
        double [:] output
        double cb
        double sb
        double cg
        double sg

    beta = input[0]
    gamma = input[1]

    with gil:
        output = np.zeros(9)

    cb = cos(beta)
    sb = sin(beta)
    cg = cos(gamma)
    sg = sin(gamma)

    output[0] = cb*cg
    output[1] = -sg
    output[2] = cg*sb
    output[3] = cb*sg
    output[4] = cg
    output[5] = sb*sg
    output[6] = -sb
    output[7] = 0
    output[8] = cb

    with gil:

        return np.reshape(output,(3,3))