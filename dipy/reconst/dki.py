#!/usr/bin/python
""" Classes and functions for fitting tensors """
from __future__ import division, print_function, absolute_import

import warnings

import numpy as np

import scipy.optimize as opt

from dipy.reconst.dti import (TensorFit, fractional_anisotropy, 
                              geodesic_anisotropy, mean_diffusivity,
                              axial_diffusivity, radial_diffusivity, trace,
                              color_fa, determinant, isotropic, deviatoric,
                              norm, mode, linearity, planarity, sphericity,
                              apparent_diffusion_coef, from_lower_triangular,
                              lower_triangular, decompose_tensor)
from dipy.utils.six.moves import range
from dipy.data import get_sphere
from ..core.gradients import gradient_table
from ..core.geometry import vector_norm
from ..core.sphere import Sphere
from .vec_val_sum import vec_val_vect
from ..core.onetime import auto_attr
from .base import ReconstModel


#Definition of quantities necessary to evaluates elements of kurtosis
#   
#    All the following definitions are needed for the evaluation of the 
#    Tensor-Derived Kurtosis Measures [1]
#
#    Parameters
#    ----------
#    a,b,c: array-like
#        Eigenvalues of a diffusion tensor equivalento to (evals[0],evals[1],evals[2]). shape should be (...,3).
#
#   Returns
#    -------
#    parameters : array-like
#        Various parameters for the evaluation of the kurtosis tensor.
#        
#        References
#        ----------
#           [1] Tabesh, A., Jensen, J.H., Ardekani, B.A., Helpern, J.A., 2011.
#           Estimation of tensors and tensor-derived measures in diffusional
#           kurtosis imaging. Magn Reson Med. 65(3), 823-836
#

def rdpython(x,y,z):
    """
    WIP
    """
   d1mach=np.zeros(5)
   d1mach[0]=1.1*10**(-308)
   d1mach[1]=8.9e307
   d1mach[2]=0.22204460*10**(-15)
   d1mach[3]=0.4440*10**(-15)
   d1mach[4]=np.log(2.0)
   errtol = (d1mach[2]/3.0)**(1.0/6.0)
   lolim  = 2.0/(d1mach[1])**(2.0/3.0)
   tuplim = d1mach[0]**(1.0/3.0)
   tuplim = (0.10*errtol)**(1.0/3.0)/tuplim
   uplim  = tuplim**2.0
   c1 = 3.0/14.0
   c2 = 1.0/6.0
   c3 = 9.0/22.0
   c4 = 3.0/26.0

   xn = x.copy()
   yn = y.copy()
   zn = z.copy()
   sigma = 0.0
   power4 = 1.0

   mu = (xn+yn+3.0*zn)*0.20
   xndev = (mu-xn)/mu
   yndev = (mu-yn)/mu
   zndev = (mu-zn)/mu
   epslon = np.max([np.abs(xndev), np.abs(yndev), np.abs(zndev)])
   while (epslon >= errtol):
      xnroot = np.sqrt(xn)
      ynroot = np.sqrt(yn)
      znroot = np.sqrt(zn)
      lamda = xnroot*(ynroot+znroot) + ynroot*znroot
      sigma = sigma + power4/(znroot*(zn+lamda))
      power4 = power4*0.250
      xn = (xn+lamda)*0.250
      yn = (yn+lamda)*0.250
      zn = (zn+lamda)*0.250
      mu = (xn+yn+3.0*zn)*0.20
      xndev = (mu-xn)/mu
      yndev = (mu-yn)/mu
      zndev = (mu-zn)/mu
      epslon = np.max([np.abs(xndev), np.abs(yndev), np.abs(zndev)])

   ea = xndev*yndev
   eb = zndev*zndev
   ec = ea - eb
   ed = ea - 6.0*eb
   ef = ed + ec + ec
   s1 = ed*(-c1+0.250*c3*ed-1.50*c4*zndev*ef)
   s2 = zndev*(c2*ef+zndev*(-c3*ec+zndev*c4*ea))
   drd = 3.0*sigma + power4*(1.0+s1+s2)/(mu*np.sqrt(mu))
   return drd



def rfpython(x,y,z):
    """
    WIP
    """
   d1mach=np.zeros(5)
   d1mach[0]=1.1*10**(-308)
   d1mach[1]=8.9e307
   d1mach[2]=0.22204460*10**(-15)
   d1mach[3]=0.4440*10**(-15)
   d1mach[4]=np.log(2.0)
   errtol = (d1mach[2]/3.0)**(1.0/6.0)
   lolim  = 2.0/(d1mach[1])**(2.0/3.0)
   tuplim = d1mach[0]**(1.0/3.0)
   tuplim = (0.10*errtol)**(1.0/3.0)/tuplim
   uplim  = tuplim**2.0
   c1 = 3.0/14.0
   c2 = 1.0/6.0
   c3 = 9.0/22.0
   c4 = 3.0/26.0

   xn = x.copy()
   yn = y.copy()
   zn = z.copy()
 
   mu = (xn+yn+zn)/3.0
   xndev = 2.0 - (mu+xn)/mu
   yndev = 2.0 - (mu+yn)/mu
   zndev = 2.0 - (mu+zn)/mu
   epslon = np.max([np.abs(xndev),np.abs(yndev),np.abs(zndev)])
   while (epslon >= errtol):
      xnroot = np.sqrt(xn)
      ynroot = np.sqrt(yn)
      znroot = np.sqrt(zn)
      lamda = xnroot*(ynroot+znroot) + ynroot*znroot
      xn = (xn+lamda)*0.250
      yn = (yn+lamda)*0.250
      zn = (zn+lamda)*0.250
      mu = (xn+yn+zn)/3.0
      xndev = 2.0 - (mu+xn)/mu
      yndev = 2.0 - (mu+yn)/mu
      zndev = 2.0 - (mu+zn)/mu
      epslon = np.max([np.abs(xndev),np.abs(yndev),np.abs(zndev)])

   e2 = xndev*yndev - zndev*zndev
   e3 = xndev*yndev*zndev
   s  = 1.0 + (c1*e2-0.10-c2*e3)*e2 + c3*e3
   drf = s/np.sqrt(mu)
   return drf


def rotatew(winit,r,iv):
    """
    WIP
    """
      gval=0.
      for i2 in range(3):
        for j2 in range(3):
          for k2 in range(3):
            for l2 in range(3):
              gval=gval+r[i2,iv[0]]*r[j2,iv[1]]*r[k2,iv[2]]*r[l2,iv[3]]*winit[i2,j2,k2,l2]
      
      return gval


def alpha(a):
    """
    WIP
    """
   alph=(1./np.sqrt(abs(a))*(np.arctan(np.sqrt(abs(a)))))
   return alph

def A1111(a,b,c):
    """
    WIP
    """
    Aarray=np.ones(a.shape)*1/5.
    abc= np.array((a, b, c))
    
    indexesxcond1=np.logical_and(np.logical_and.reduce(abc>0),np.logical_and(a!=b, b!=c))
    if np.sum(indexesxcond1)!=0:
      d=np.zeros(a.shape)
      e=np.zeros(a.shape)
      f=np.zeros(a.shape)
      g=np.zeros(a.shape)
      h=np.zeros(a.shape)
      d[indexesxcond1]=(((a[indexesxcond1]+b[indexesxcond1]+c[indexesxcond1])**2)/(18*(a[indexesxcond1]-b[indexesxcond1])*(a[indexesxcond1]-c[indexesxcond1])))
      e[indexesxcond1]=((np.sqrt(b[indexesxcond1]*c[indexesxcond1]))/a[indexesxcond1])
      f[indexesxcond1]=rfpython(a[indexesxcond1]/b[indexesxcond1],a[indexesxcond1]/c[indexesxcond1],np.ones(len(a[indexesxcond1])))
      g[indexesxcond1]=((3*a[indexesxcond1]**2-a[indexesxcond1]*b[indexesxcond1]-a[indexesxcond1]*c[indexesxcond1]-b[indexesxcond1]*c[indexesxcond1])/(3*a[indexesxcond1]*np.sqrt(b[indexesxcond1]*c[indexesxcond1])))
      h[indexesxcond1]=rdpython(a[indexesxcond1]/b[indexesxcond1],a[indexesxcond1]/c[indexesxcond1],np.ones(len(a[indexesxcond1])))
      Aarray[indexesxcond1]=d[indexesxcond1]*(e[indexesxcond1]*f[indexesxcond1]+g[indexesxcond1]*h[indexesxcond1]-1)

    indexesxcond2=np.logical_and(np.logical_and.reduce(abc>0),np.logical_and(a==b, b!=c))
    if np.sum(indexesxcond2)!=0:
      dummy2=A2233(c,a,a)
      Aarray[indexesxcond2]=3*dummy2[indexesxcond2]

    indexesxcond3=np.logical_and(np.logical_and.reduce(abc>0),np.logical_and(a==c, a!=b))
    if np.sum(indexesxcond3)!=0:
      dummy3=A2233(b,a,a)
      Aarray[indexesxcond3]=3*dummy3[indexesxcond3]

### the following condition has to be checked ###
    indexesxcond4=np.logical_or.reduce(abc<=0)
    Aarray[indexesxcond4]=0   
    return Aarray
  
def A2233(a,b,c):
    """
    WIP
    """
    Aarray=np.ones(a.shape)*1/15.
    abc= np.array((a, b, c))
    
    indexesxcond1=np.logical_and(np.logical_and.reduce(abc>0),(b!=c))
    if np.sum(indexesxcond1)!=0:
      d=np.zeros(a.shape)
      e=np.zeros(a.shape)
      f=np.zeros(a.shape)
      g=np.zeros(a.shape)
      h=np.zeros(a.shape)
      d[indexesxcond1]=(((a[indexesxcond1]+b[indexesxcond1]+c[indexesxcond1])**2)/(3*(b[indexesxcond1]-c[indexesxcond1])**2))
      e[indexesxcond1]=((b[indexesxcond1]+c[indexesxcond1])/(np.sqrt(b[indexesxcond1]*c[indexesxcond1])))
      f[indexesxcond1]=rfpython(a[indexesxcond1]/b[indexesxcond1],a[indexesxcond1]/c[indexesxcond1],np.ones(len(a[indexesxcond1])))
      g[indexesxcond1]=((2*a[indexesxcond1]-b[indexesxcond1]-c[indexesxcond1])/(3*np.sqrt(b[indexesxcond1]*c[indexesxcond1])))
      h[indexesxcond1]=rdpython(a[indexesxcond1]/b[indexesxcond1],a[indexesxcond1]/c[indexesxcond1],np.ones(len(a[indexesxcond1])))
      Aarray[indexesxcond1]=(1/6.)*d[indexesxcond1]*(e[indexesxcond1]*f[indexesxcond1]+g[indexesxcond1]*h[indexesxcond1]-2)


    indexesxcond2=np.logical_and(np.logical_and.reduce(abc>0),np.logical_and(b==c, a!=b))
    if np.sum(indexesxcond2)!=0:
      d=np.zeros(a.shape)
      e=np.zeros(a.shape)
      f=np.zeros(a.shape)
      g=np.zeros(a.shape)
      d[indexesxcond2]=(((a[indexesxcond2]+2.*c[indexesxcond2])**2)/(144.*c[indexesxcond2]**2*(a[indexesxcond2]-c[indexesxcond2])**2))
      e[indexesxcond2]=c[indexesxcond2]*(a[indexesxcond2]+2.*c[indexesxcond2])
      f[indexesxcond2]=a[indexesxcond2]*(a[indexesxcond2]-4.*c[indexesxcond2])
      g[indexesxcond2]=alpha(1.-(a[indexesxcond2]/c[indexesxcond2]))
      Aarray[indexesxcond2]=d[indexesxcond2]*(e[indexesxcond2]+f[indexesxcond2]*g[indexesxcond2])
   
  ### the following condition has to be checked ###
    indexesxcond3=np.logical_or.reduce(abc<=0)
    Aarray[indexesxcond3]=0   
    return Aarray  

def C2222(a,b,c):
    """
    WIP
    """
    Carray=np.zeros(a.shape)
    abc= np.array((a, b, c))
    indexesxcond1=np.logical_and.reduce(abc>0)
    if np.sum(indexesxcond1)!=0:
      Carray[indexesxcond1]=((a[indexesxcond1]+2.*b[indexesxcond1])**2/(24.*b[indexesxcond1]**2))
    
    indexesxcond2=np.logical_and(np.logical_and.reduce(abc>0),(b!=c))
    if np.sum(indexesxcond2)!=0:
      Carray[indexesxcond2]=(((a[indexesxcond2]+b[indexesxcond2]+c[indexesxcond2])**2/((18.)*(b[indexesxcond2])*(b[indexesxcond2]-c[indexesxcond2])**2))*(2.*b[indexesxcond2]+((c[indexesxcond2]**2-3.*b[indexesxcond2]*c[indexesxcond2])/(np.sqrt(b[indexesxcond2]*c[indexesxcond2])))))

  ### the following condition has to be checked ###
    indexesxcond3=np.logical_or.reduce(abc<=0)
    Carray[indexesxcond3]=0   
    return Carray  

def C2233(a,b,c):
    """
    WIP
    """
    Carray=np.zeros(a.shape)
    abc= np.array((a, b, c))
    
    indexesxcond1=np.logical_and.reduce(abc>0)
    if np.sum(indexesxcond1)!=0:
      Carray[indexesxcond1]=((a[indexesxcond1]+2.*b[indexesxcond1])**2/(12.*b[indexesxcond1]**2))
      
    indexesxcond2=np.logical_and(np.logical_and.reduce(abc>0),(b!=c))
    if np.sum(indexesxcond2)!=0:
      Carray[indexesxcond2]=(((a[indexesxcond2]+b[indexesxcond2]+c[indexesxcond2])**2/((3.)*(b[indexesxcond2]-c[indexesxcond2])**2))*(((b[indexesxcond2]+c[indexesxcond2])/(np.sqrt(b[indexesxcond2]*c[indexesxcond2])))-2.))

  ### the following condition has to be checked ###
    indexesxcond3=np.logical_or.reduce(abc<=0)
    Carray[indexesxcond3]=0   
    return Carray  


def F1m(a,b,c):
    """
    WIP
    """
        A=A1111(a,b,c)
        return A

def F2m(a,b,c):
    """
    WIP
    """
        A=6*A2233(a,b,c)
        return 6*A2233(a,b,c)

def G1m(a,b,c):
    """
    WIP
    """
    	return C2222(a,b,c)

def G2m(a,b,c):
    """
    WIP
    """
    return 6*C2233(a,b,c)



def _roll_Wrotat(Wrotat, axis=-1):
    """
    (WIP)
    
    Helper function to check that the values of the W tensors rotated (needed
    for evaluation of the kurtosis quantities) provided to functions
    calculating tensor statistics have the right shape

    Parameters
    ----------
    Wrotat : array-like
        Values of a W tensor rotated. shape should be (...,6).

    axis : int
        The axis of the array which contains the 6 values. Default: -1

    Returns
    -------
    Wrotat : array-like
        Values of a W tensor rotated, rolled so that the 6 values are
        the last axis.
    """
    if Wrotat.shape[-1] != 3:
        msg = "Expecting 6 W tensor values, got {}".format(Wrotat.shape[-1])
        raise ValueError(msg)

    Wrotat = np.rollaxis(Wrotat, axis)

    return Wrotat

def mean_kurtosis(evals, Wrotat, axis=-1):
    r"""
    (WIP)
    
    Mean Kurtosis (MK) of a diffusion kurtosis tensor. 

    Parameters
    ----------
    evals : array-like
        Eigenvalues of a diffusion tensor.
    Wrotat : array-like
        W tensor elements of interest for the evaluation of the Kurtosis 
        (W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz)
    axis : int
        Axis of `evals` which contains 3 eigenvalues.

    Returns
    -------
    mk : array
        Calculated MK.

    Notes
    --------
    MK is calculated with the following equation:

    .. math::

    \begin{multline}
     MK=F_1(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{1111}+F_1(\lambda_2,\lambda_1,\lambda_3)\hat{W}_{2222}+F_1(\lambda_3,\lambda_2,\lambda_1)\hat{W}_{3333}+ \\
     F_2(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2233}+F_2(\lambda_2,\lambda_1,\lambda_3)\hat{W}_{1133}+F_2(\lambda_3,\lambda_2,\lambda_1)\hat{W}_{1122}
     \end{multline}
     where $\hat{W}_{ijkl}$ are the components of the $W$ tensor in the coordinates system defined by the eigenvectors of the diffusion tensor $\mathbf{D}$ and 
 
    \begin{multline}
     F_1(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{18(\lambda_1-\lambda_2)(\lambda_1-\lambda_3)}[\frac{\sqrt{\lambda_2\lambda_3}}{\lambda_1}R_F(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)+\\
     \frac{3\lambda_1^2-\lambda_1\lambda_2-\lambda_2\lambda_3-\lambda_1\lambda_3}{3\lambda_1 \sqrt{\lambda_2 \lambda_3}}R_D(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)-1 ]
    \end{multline}

    \begin{multline}
     F_2(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{3(\lambda_2-\lambda_3)^2}[\frac{\lambda_2+\lambda_3}{\sqrt{\lambda_2\lambda_3}}R_F(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)+\\
     \frac{2\lambda_1-\lambda_2-\lambda_3}{3\sqrt{\lambda_2 \lambda_3}}R_D(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)-2]
    \end{multline}
    where $R_f$ and $R_d$ are the Carlson's elliptic integrals.


    """
    [W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz]=[Wrotat[...,0],Wrotat[...,1],Wrotat[...,2],Wrotat[...,3],Wrotat[...,4],Wrotat[...,5]]
    MeanKurt=F1m(evals[...,0],evals[...,1],evals[...,2])*W_xxxx+F1m(evals[...,1],evals[...,0],evals[...,2])*W_yyyy+F1m(evals[...,2],evals[...,1],evals[...,0])*W_zzzz+F2m(evals[...,0],evals[...,1],evals[...,2])*W_yyzz+F2m(evals[...,1],evals[...,0],evals[...,2])*W_xxzz+F2m(evals[...,2],evals[...,1],evals[...,0])*W_xxyy
    return MeanKurt


def axial_kurtosis(evals, Wrotat, axis=-1):
    r"""
    (WIP)    
    
    Axial Kurtosis (AK) of a diffusion kurtosis tensor. 

    Parameters
    ----------
    evals : array-like
        Eigenvalues of a diffusion tensor.
    Wrotat : array-like
        W tensor elements of interest for the evaluation of the Kurtosis 
        (W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz)
    axis : int
        Axis of `evals` which contains 3 eigenvalues.

    Returns
    -------
    ak : array
        Calculated AK.

    Notes
    --------
    AK is calculated with the following equation:

    .. math::

     K_{||}=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{9\lambda_1^2}
     \hat{W}_{1111}

    """
    [W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz]=[Wrotat[...,0],Wrotat[...,1],Wrotat[...,1],Wrotat[...,3],Wrotat[...,4],Wrotat[...,5]]
    AxialKurt=((evals[...,0]+evals[...,1]+evals[...,2])**2/(9*(evals[...,0])**2))*W_xxxx
    return AxialKurt


def radial_kurtosis(evals, Wrotat, axis=-1):
    r"""
    (WIP)
    
    Radial Kurtosis (RK) of a diffusion kurtosis tensor. 

    Parameters
    ----------
    evals : array-like
        Eigenvalues of a diffusion tensor.
    Wrotat : array-like
        W tensor elements of interest for the evaluation of the Kurtosis (W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz)
    axis : int
        Axis of `evals` which contains 3 eigenvalues.

    Returns
    -------
    rk : array
        Calculated RK.

    Notes
    --------
    RK is calculated with the following equation:

    .. math::


    K_{r}=G_1(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2222}+G_1(\lambda_1,\lambda_3,\lambda_2)\hat{W}_{333}+G_2(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2233}

    where:
    \begin{equation}
    G_1(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{18\lambda_2(\lambda_2-\lambda_3)}[2\lambda_2+\frac{\lambda_3^2-3\lambda_2 \lambda_3}{\sqrt{\lambda_2\lambda_3}}]
    \end{equation}

    \begin{equation}
    G_2(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{(\lambda_2-\lambda_3)^2}[\frac{\lambda_2+\lambda_3}{\sqrt{\lambda_2\lambda_3}}-2]
    \end{equation}


    """
    [W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz]=[Wrotat[...,0],Wrotat[...,1],Wrotat[...,1],Wrotat[...,3],Wrotat[...,4],Wrotat[...,5]]

    RadKurt=G1m(evals[...,0],evals[...,1],evals[...,2])*W_yyyy+G1m(evals[...,0],evals[...,2],evals[...,1])*W_zzzz+G2m(evals[...,0],evals[...,1],evals[...,2])*W_yyzz     
    return RadKurt
#End of the definitions of quantities necessary to evaluates elements of kurtosis


class DKIModel(ReconstModel):
    """ Diffusion Kurtosis Tensor
    """
    def __init__(self, gtab, fit_method="OLS_DKI", *args, **kwargs):
        """ Diffusion Kurtosis Tensor Model [1]

        Parameters
        ----------
        gtab : GradientTable class instance

        fit_method : str or callable
            str can be one of the following:
            'OLS_DKI' or 'ULLS_DKI' for ordinary least squares
                dki.ols_fit_dki
            'WLS_DKI' or 'UWLLS_DKI' for weighted ordinary least squares
                dki.wls_fit_dki

            callable has to have the signature:
                fit_method(design_matrix, data, *args, **kwargs)

        args, kwargs : arguments and key-word arguments passed to the
           fit_method. See dki.ols_fit_dki, dki.wls_fit_dki for details

        References
        ----------
           [1] Tabesh, A., Jensen, J.H., Ardekani, B.A., Helpern, J.A., 2011.
           Estimation of tensors and tensor-derived measures in diffusional
           kurtosis imaging. Magn Reson Med. 65(3), 823-836
        """
        ReconstModel.__init__(self, gtab)

        if not callable(fit_method):
            try:
                self.fit_method = common_fit_methods[fit_method]
            except KeyError:
                raise ValueError('"' + str(fit_method) + '" is not a known fit '
                                 'method, the fit method should either be a '
                                 'function or one of the common fit methods')

        self.design_matrix = dki_design_matrix(self.gtab)
        self.args = args
        self.kwargs = kwargs


    def fit(self, data, mask=None):
        """ Fit method of the DKI model class

        Parameters
        ----------
        data : array
            The measured signal from one voxel.

        mask : array
            A boolean array used to mark the coordinates in the data that
            should be analyzed that has the shape data.shape[-1]
        """
        # If a mask is provided, we will use it to access the data
        if mask is not None:
            # Make sure it's boolean, so that it can be used to mask
            mask = np.array(mask, dtype=bool, copy=False)
            data_in_mask = data[mask]
        else:
            data_in_mask = data

        params_in_mask = self.fit_method(self.design_matrix, data_in_mask,
                                         *self.args, **self.kwargs)

        if mask is None:
            out_shape = data.shape[:-1] + (-1, )
            dki_params = params_in_mask.reshape(out_shape)
        else:
            dki_params = np.zeros(data.shape[:-1] + (27,))
            dki_params[mask, :] = params_in_mask

        return DKIFit(self, dki_params)


class DKIFit(TensorFit):

    def __init__(self, model, model_params):
        """ Initialize a DKIFit class instance. 
        
        Since DKI is an extension of DTI, class instance is defined as a
        subclass of the TensorFit from dti.py
        """
        TensorFit.__init__(self, model, model_params)

    @property
    def Wrotat(self):
        """
        (WIP)
        Returns the values of the k tensors as an array
        """
        return self.model_params[..., 12:]

    @auto_attr
    def mk(self):
      r"""
      (WIP)
      Mean Kurtosis (MK) of a diffusion kurtosis tensor. 

      Returns
      -------
      mk : array
          Calculated MK.

      Notes
      --------
      MK is calculated with the following equation:

      .. math::

      \begin{multline}
      MK=F_1(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{1111}+F_1(\lambda_2,\lambda_1,\lambda_3)\hat{W}_{2222}+F_1(\lambda_3,\lambda_2,\lambda_1)\hat{W}_{3333}+ \\
      F_2(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2233}+F_2(\lambda_2,\lambda_1,\lambda_3)\hat{W}_{1133}+F_2(\lambda_3,\lambda_2,\lambda_1)\hat{W}_{1122}
      \end{multline}
      where $\hat{W}_{ijkl}$ are the components of the $W$ tensor in the coordinates system defined by the eigenvectors of the diffusion tensor $\mathbf{D}$ and 
 
      \begin{multline}
      F_1(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{18(\lambda_1-\lambda_2)(\lambda_1-\lambda_3)}[\frac{\sqrt{\lambda_2\lambda_3}}{\lambda_1}R_F(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)+\\
      \frac{3\lambda_1^2-\lambda_1\lambda_2-\lambda_2\lambda_3-\lambda_1\lambda_3}{3\lambda_1 \sqrt{\lambda_2 \lambda_3}}R_D(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)-1 ]
      \end{multline}

      \begin{multline}
      F_2(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{3(\lambda_2-\lambda_3)^2}[\frac{\lambda_2+\lambda_3}{\sqrt{\lambda_2\lambda_3}}R_F(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)+\\
      \frac{2\lambda_1-\lambda_2-\lambda_3}{3\sqrt{\lambda_2 \lambda_3}}R_D(\frac{\lambda_1}{\lambda_2},\frac{\lambda_1}{\lambda_3},1)-2]
      \end{multline}
      where $R_f$ and $R_d$ are the Carlson's elliptic integrals.

      """
      return mean_kurtosis(self.evals, self.Wrotat)

    @auto_attr
    def ak(evals, Wrotat, axis=-1):
        r"""
        (WIP)
        Axial Kurtosis (AK) of a diffusion kurtosis tensor. 

        Parameters
        ----------
        evals : array-like
            Eigenvalues of a diffusion tensor.
        Wrotat : array-like
            W tensor elements of interest for the evaluation of the Kurtosis (W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz)
        axis : int
            Axis of `evals` which contains 3 eigenvalues.

        Returns
        -------
        ak : array
            Calculated AK.

        Notes
        --------
        AK is calculated with the following equation:

        .. math::

        K_{||}=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{9\lambda_1^2}\hat{W}_{1111}

        """
        return axial_kurtosis(self.evals, self.Wrotat)

    @auto_attr
    def rk(evals, Wrotat, axis=-1):
        r"""
        (WIP)
        Radial Kurtosis (RK) of a diffusion kurtosis tensor. 

        Parameters
        ----------
        evals : array-like
            Eigenvalues of a diffusion tensor.
        Wrotat : array-like
            W tensor elements of interest for the evaluation of the Kurtosis (W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz)
        axis : int
            Axis of `evals` which contains 3 eigenvalues.

        Returns
        -------
        rk : array
            Calculated RK.

        Notes
        --------
        RK is calculated with the following equation:

        .. math::

        K_{r}=G_1(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2222}+G_1(\lambda_1,\lambda_3,\lambda_2)\hat{W}_{333}+G_2(\lambda_1,\lambda_2,\lambda_3)\hat{W}_{2233}

        where:
        \begin{equation}
        G_1(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{18\lambda_2(\lambda_2-\lambda_3)}[2\lambda_2+\frac{\lambda_3^2-3\lambda_2 \lambda_3}{\sqrt{\lambda_2\lambda_3}}]
        \end{equation}

        \begin{equation}
        G_2(\lambda_1,\lambda_2,\lambda_3)=\frac{(\lambda_1+\lambda_2+\lambda_3)^2}{(\lambda_2-\lambda_3)^2}[\frac{\lambda_2+\lambda_3}{\sqrt{\lambda_2\lambda_3}}-2]
        \end{equation}

        """
        return radial_kurtosis(self.evals, self.Wrotat)

    def DKI_predict(self, gtab, S0=1):
        r"""
        (WIP)   
        """


def ols_fit_dki(design_matrix, data, min_signal=1):
    r"""
    Computes ordinary least squares (OLS) fit to calculate the diffusion
    tensor and kurtosis tensor using a linear regression diffusion kurtosis
    model [1]_.
    
    Parameters
    ----------
    design_matrix : array (g, 22)
        Design matrix holding the covariants used to solve for the regression
        coefficients.
    data : array ([X, Y, Z, ...], g) or array ([N, ...], g)
        Data or response variables holding the data. Note that the last
        dimension should contain the data. It makes no copies of data.
    min_signal : default = 1
        All values below min_signal are repalced with min_signal. This is done
        in order to avoid taking log(0) durring the tensor fitting.

    Returns
    -------
    dki_params : array (N, 27)
        All parameters estimated from the diffusion kurtosis model for all N
        voxels. 
        Parameters are ordered as follow:
            1) Three diffusion tensor's eingenvalues
            2) Three lines of the eigenvector matrix each containing the first
               second and third cordinates of the eigenvector
            3) Fifteen elements of the kurtosis tensor

    See Also
    --------
    wls_fit_dki

    References
    ----------
       [1] Tabesh, A., Jensen, J.H., Ardekani, B.A., Helpern, J.A., 2011.
           Estimation of tensors and tensor-derived measures in diffusional
           kurtosis imaging. Magn Reson Med. 65(3), 823-836
    """

    tol = 1e-6
    if min_signal <= 0:
        raise ValueError('min_signal must be > 0')

    # preparing data and initializing parameters
    data = np.asarray(data)
    data_flat = data.reshape((-1, data.shape[-1]))
    dki_params = np.empty((len(data_flat), 27))
    
    # inverting design matrix and defining minimun diffusion aloud
    min_diffusivity = tol / -design_matrix.min()
    inv_design = np.linalg.pinv(design_matrix)

    # lopping OLS solution on all data voxels
    for vox in range(len(data_flat)):
        dki_params[vox] = _ols_iter(inv_design, data_flat[vox], min_signal,
                                    min_diffusivity)
    
    return dki_params


def _ols_iter(inv_design, sig, min_signal, min_diffusivity):
    ''' Helper function used by ols_fit_dki - Applies OLS fit of the diffusion
    kurtosis model to single voxel signals.
    
    Parameters
    ----------
    inv_design : array (g, 22)
        Inverse of the design matrix holding the covariants used to solve for
        the regression coefficients.
    sig : array (g, ) or array ([N, ...], g)
        Diffusion-weighted signal for a single voxel data.
    min_signal : 
        All values below min_signal are repalced with min_signal. This is done
        in order to avoid taking log(0) durring the tensor fitting.
    min_diffusivity : float
        Because negative eigenvalues are not physical and small eigenvalues,
        much smaller than the diffusion weighting, cause quite a lot of noise
        in metrics such as fa, diffusivity values smaller than
        `min_diffusivity` are replaced with `min_diffusivity`.

    Returns
    -------
    dki_params : array (27, )
        All parameters estimated from the diffusion kurtosis model.
        Parameters are ordered as follow:
            1) Three diffusion tensor's eingenvalues
            2) Three lines of the eigenvector matrix each containing the first
               second and third cordinates of the eigenvector
            3) Fifteen elements of the kurtosis tensor
    '''

    # removing small signals
    sig = np.maximum(sig, min_signal)

    # DKI ordinary linear least square solution
    log_s = np.log(sig)
    result = np.dot(inv_design, log_s)

    # Extracting the diffusion tensor parameters from solution
    DT_elements = result[:6]
    evals, evecs = decompose_tensor(from_lower_triangular(DT_elements),
                                    min_diffusivity=min_diffusivity)

    # Extracting kurtosis tensor parameters from solution
    MD_square = (evals.mean(0))**2  
    KT_elements = result[6:21] / MD_square

    # Write output  
    dki_params = np.concatenate((evals, evecs[0], evecs[1], evecs[2], 
                                 KT_elements), axis=0)

    return dki_params


def wls_fit_dki(design_matrix, data, min_signal=1):
    r"""
    Computes weighted linear least squares (WLS) fit to calculate
    the diffusion tensor and kurtosis tensor using a weighted linear 
    regression diffusion kurtosis model [1]_.

    Parameters
    ----------
    design_matrix : array (g, 22)
        Design matrix holding the covariants used to solve for the regression
        coefficients.
    data : array ([X, Y, Z, ...], g) or array ([N, ...], g)
        Data or response variables holding the data. Note that the last
        dimension should contain the data. It makes no copies of data.
    min_signal : default = 1
        All values below min_signal are repalced with min_signal. This is done
        in order to avoid taking log(0) durring the tensor fitting.

    Returns
    -------
    dki_params : array (N, 27)
        All parameters estimated from the diffusion kurtosis model for all N
        voxels. 
        Parameters are ordered as follow:
            1) Three diffusion tensor's eingenvalues
            2) Three lines of the eigenvector matrix each containing the first
               second and third cordinates of the eigenvector
            3) Fifteen elements of the kurtosis tensor 

    See Also
    --------
    decompose_tensors


    References
    ----------
       [1] Tabesh, A., Jensen, J.H., Ardekani, B.A., Helpern, J.A., 2011.
           Estimation of tensors and tensor-derived measures in diffusional
           kurtosis imaging. Magn Reson Med. 65(3), 823-836
    """

    tol = 1e-6
    if min_signal <= 0:
        raise ValueError('min_signal must be > 0')

    # preparing data and initializing parametres
    data = np.asarray(data)
    data_flat = data.reshape((-1, data.shape[-1]))
    dki_params = np.empty((len(data_flat), 6, 3))

    # defining minimun diffusion aloud 
    min_diffusivity = tol / -design_matrix.min()

    ols_fit = _ols_fit_matrix(design_matrix)
   
    for param, sig in zip(dki_params, data_flat):
        param[0], param[1:4], param[4], param[5] = _wls_iter(ols_fit, design_matrix, sig, min_signal, min_diffusivity)
        
    dki_params.shape=data.shape[:-1]+(18,)
    dki_params=dki_params
    return dki_params



def _ols_fit_matrix(design_matrix):
    """
    Helper function to calculate the ordinary least squares (OLS)
    fit as a matrix multiplication. Mainly used to calculate WLS weights. Can
    be used to calculate regression coefficients in OLS but not recommended.

    See Also:
    ---------
    wls_fit_tensor, ols_fit_tensor

    Example:
    --------
    ols_fit = _ols_fit_matrix(design_mat)
    ols_data = np.dot(ols_fit, data)
    """

    U, S, V = np.linalg.svd(design_matrix, False)
    return np.dot(U, U.T)



def _wls_iter(ols_fit, design_matrix, sig, min_signal, min_diffusivity):
    ''' Helper function used by wls_fit_tensor.
    '''
    sig = np.maximum(sig, min_signal)  # throw out zero signals
    log_s = np.log(sig)
    w = np.exp(np.dot(ols_fit, log_s))
    result = np.dot(np.linalg.pinv(design_matrix * w[:, None]), w * log_s)
    D=result[:6]
    tensor=from_lower_triangular(D)
    MeanD_square=((tensor[0,0]+tensor[1,1]+tensor[2,2])/3.)**2  
    K_tensor_elements=result[6:21]/MeanD_square
    return ambiguous_function_decompose_tensors(tensor, K_tensor_elements, min_diffusivity=min_diffusivity)


"""

def _ols_iter(inv_design, sig, min_signal, min_diffusivity):
    ''' Helper function used by ols_fit_tensor.
    '''
    sig = np.maximum(sig, min_signal)  # throw out zero signals
    log_s = np.log(sig)
    D = np.dot(inv_design, log_s)
    tensor = from_lower_triangular(D)
    return decompose_tensor(tensor, min_diffusivity=min_diffusivity)


def _wls_iter(weighted_matrix,design_matrix,inv_design,sig,min_signal,min_diffusivity):
    ''' Helper function used by wls_fit_dki to calculate the weights' matrix.
    '''
    sig=np.maximum(sig,min_signal)  # throw out zero signals
    print('sig.shape',sig.shape)
    log_s = np.log(sig)
    betaols=np.dot(inv_design,log_s)
    print('design_matrix.shape',design_matrix.shape)
    print('inv_design.shape',inv_design.shape) 
    print('betaols.shape',betaols.shape)
    muols=np.dot(design_matrix,betaols)  
    print('muols.shape',muols.shape)
    estimated_signals=np.exp(muols)  
    w=np.dot(weighted_matrix,estimated_signals**2) 
    weighted_inverseB_matrix=np.linalg.pinv(B*w[:,None])
    result=np.dot(weighted_inverseB_matrix,w*log_s) 
    D=result[:6]
    tensor=from_lower_triangular(D)
    MeanD_square=((tensor[0,0]+tensor[1,1]+tensor[2,2])/3.)**2  
    K_tensor_elements=result[6:21]/MeanD_square
    return decompose_tensors(tensor, K_tensor_elements, min_diffusivity=min_diffusivity)

def weighted_matrix_form(B):
    ''' Helper function used by wls_fit_dki to calculate the weights' matrix.
    '''
    A=np.ones((B.shape[0],B.shape[0]))
    C=np.linalg.matrix_power(A,0)
    return C

"""


def ambiguous_function_decompose_tensors(tensor, K_tensor_elements, min_diffusivity=0):
    """ Returns eigenvalues and eigenvectors given a diffusion tensor

    Computes tensor eigen decomposition to calculate eigenvalues and
    eigenvectors (Basser et al., 1994a).

    Parameters
    ----------
    tensor : array (3, 3)
        Hermitian matrix representing a diffusion tensor.
    K_tensor_elements : array(15,1)
        Independent elements of the K tensors
    min_diffusivity : float
        Because negative eigenvalues are not physical and small eigenvalues,
        much smaller than the diffusion weighting, cause quite a lot of noise
        in metrics such as fa, diffusivity values smaller than
        `min_diffusivity` are replaced with `min_diffusivity`.

    Returns
    -------
    eigvals : array (3,)
        Eigenvalues from eigen decomposition of the tensor. Negative
        eigenvalues are replaced by zero. Sorted from largest to smallest.
    eigvecs : array (3, 3)
        Associated eigenvectors from eigen decomposition of the tensor.
        Eigenvectors are columnar (e.g. eigvecs[:,j] is associated with
        eigvals[j])

    """
    #outputs multiplicity as well so need to unique
    eigenvals, eigenvecs = np.linalg.eigh(tensor)

    #need to sort the eigenvalues and associated eigenvectors
    order = eigenvals.argsort()[::-1]
    eigenvecs = eigenvecs[:, order]
    eigenvals = eigenvals[order]

    eigenvals = eigenvals.clip(min=min_diffusivity)
    # eigenvecs: each vector is columnar

    [Wxxxx,Wyyyy,Wzzzz,Wxxxy,Wxxxz,Wxyyy,Wyyyz,Wxzzz,Wyzzz,Wxxyy,Wxxzz,Wyyzz,Wxxyz,Wxyyz,Wxyzz]=K_tensor_elements
    Wrot=np.zeros([3,3,3,3])
    Wfit=np.zeros([3,3,3,3])
    Wfit[0,0,0,0]=Wxxxx
    Wfit[1,1,1,1]=Wyyyy
    Wfit[2,2,2,2]=Wzzzz
    Wfit[0,0,0,1]=Wfit[0,0,1,0]=Wfit[0,1,0,0]=Wfit[1,0,0,0]=Wxxxy
    Wfit[0,0,0,2]=Wfit[0,0,2,0]=Wfit[0,2,0,0]=Wfit[2,0,0,0]=Wxxxz
    Wfit[1,2,2,2]=Wfit[2,2,2,1]=Wfit[2,1,2,2]=Wfit[2,2,1,2]=Wyzzz
    Wfit[0,2,2,2]=Wfit[2,2,2,0]=Wfit[2,0,2,2]=Wfit[2,2,0,2]=Wxzzz
    Wfit[0,1,1,1]=Wfit[1,0,1,1]=Wfit[1,1,1,0]=Wfit[1,1,0,1]=Wxyyy
    Wfit[1,1,1,2]=Wfit[1,2,1,1]=Wfit[2,1,1,1]=Wfit[1,1,2,1]=Wyyyz
    Wfit[0,0,1,1]=Wfit[0,1,0,1]=Wfit[0,1,1,0]=Wfit[1,0,0,1]=Wfit[1,0,1,0]=Wfit[1,1,0,0]=Wxxyy 
    Wfit[0,0,2,2]=Wfit[0,2,0,2]=Wfit[0,2,2,0]=Wfit[2,0,0,2]=Wfit[2,0,2,0]=Wfit[2,2,0,0]=Wxxzz 
    Wfit[1,1,2,2]=Wfit[1,2,1,2]=Wfit[1,2,2,1]=Wfit[2,1,1,2]=Wfit[2,2,1,1]=Wfit[2,1,2,1]=Wyyzz 
    Wfit[0,0,1,2]=Wfit[0,0,2,1]=Wfit[0,1,0,2]=Wfit[0,1,2,0]=Wfit[0,2,0,1]=Wfit[0,2,1,0]=Wfit[1,0,0,2]=Wfit[1,0,2,0]=Wfit[1,2,0,0]=Wfit[2,0,0,1]=Wfit[2,0,1,0]=Wfit[2,1,0,0]=Wxxyz
    Wfit[0,1,1,2]=Wfit[0,1,2,1]=Wfit[0,2,1,1]=Wfit[1,0,1,2]=Wfit[1,1,0,2]=Wfit[1,1,2,0]=Wfit[1,2,0,1]=Wfit[1,2,1,0]=Wfit[2,0,1,1]=Wfit[2,1,0,1]=Wfit[2,1,1,0]=Wfit[1,0,2,1]=Wxyyz
    Wfit[0,1,2,2]=Wfit[0,2,1,2]=Wfit[0,2,2,1]=Wfit[1,0,2,2]=Wfit[1,2,0,2]=Wfit[1,2,2,0]=Wfit[2,0,1,2]=Wfit[2,0,2,1]=Wfit[2,1,0,2]=Wfit[2,1,2,0]=Wfit[2,2,0,1]=Wfit[2,2,1,0]=Wxyzz

    indexarray=[[0,0,0,0],[1,1,1,1],[2,2,2,2],[0,0,1,1],[0,0,2,2],[1,1,2,2]]
    Wrotat=[0,0,0,0,0,0]
    for indval in range(len(indexarray)):
         	Wrotat[indval]=rotatew(Wfit,eigenvecs,indexarray[indval])
         	[W_xxxx,W_yyyy,W_zzzz,W_xxyy,W_xxzz,W_yyzz]=Wrotat

    return eigenvals, eigenvecs, Wrotat[:3],Wrotat[3:]



def dki_design_matrix(gtab):
    r""" Constructs B design matrix for DKI

    Parameters
    ---------
    gtab : GradientTable
        Measurement directions.

    Returns
    -------
    B : array (N,22)
        Design matrix or B matrix for the DKI model
        B[j, :] = (Bxx, Bxy, Bzz, Bxz, Byz, Bzz,
                   Bxxxx, Byyyy, Bzzzz, Bxxxy, Bxxxz,
                   Bxyyy, Byyyz, Bxzzz, Byzzz, Bxxyy,
                   Bxxzz, Byyzz, Bxxyz, Bxyyz, Bxyzz,
                   BlogS0)
    """
    b = gtab.bvals
    bvec = gtab.bvecs

    B = np.zeros((len(b), 22))
    B[:, 0] = -b * bvec[:, 0] * bvec[:, 0]
    B[:, 1] = -2 * b * bvec[:, 0] * bvec[:, 1]
    B[:, 2] = -b * bvec[:, 1] * bvec[:, 1]
    B[:, 3] = -2 * b * bvec[:, 0] * bvec[:, 2]
    B[:, 4] = -2 * b * bvec[:, 1] * bvec[:, 2]
    B[:, 5] = -b * bvec[:, 2] * bvec[:, 2]
    B[:, 6] = b * b * bvec[:, 0]**4 / 6
    B[:, 7] = b * b * bvec[:, 1]**4 / 6
    B[:, 8] = b * b * bvec[:, 2]**4 / 6
    B[:, 9] = 4 * b * b * bvec[:, 0]**3 * bvec[:, 1] / 6
    B[:, 10] = 4 * b * b * bvec[:, 0]**3 * bvec[:, 2] / 6
    B[:, 11] = 4 * b * b * bvec[:, 1]**3 * bvec[:, 0] / 6
    B[:, 12] = 4 * b * b * bvec[:, 1]**3 * bvec[:, 2] / 6
    B[:, 13] = 4 * b * b * bvec[:, 2]**3 * bvec[:, 0] / 6
    B[:, 14] = 4 * b * b * bvec[:, 2]**3 * bvec[:, 1] / 6
    B[:, 15] = b * b * bvec[:, 0]**2 * bvec[:, 1]**2
    B[:, 16] = b * b * bvec[:, 0]**2 * bvec[:, 2]**2
    B[:, 17] = b * b * bvec[:, 1]**2 * bvec[:, 2]**2
    B[:, 18] = 2 * b * b * bvec[:, 0]**2 * bvec[:, 1] * bvec[:, 2]
    B[:, 19] = 2 * b * b * bvec[:, 1]**2 * bvec[:, 0] * bvec[:, 2]
    B[:, 20] = 2 * b * b * bvec[:, 2]**2 * bvec[:, 0] * bvec[:, 1]
    B[:, 21] = np.ones(len(b))

    return B


def quantize_evecs(evecs, odf_vertices=None):
    """ Find the closest orientation of an evenly distributed sphere

    Parameters
    ----------
    evecs : ndarray
    odf_vertices : None or ndarray
        If None, then set vertices from symmetric362 sphere.  Otherwise use
        passed ndarray as vertices

    Returns
    -------
    IN : ndarray
    """
    max_evecs = evecs[..., :, 0]
    if odf_vertices == None:
        odf_vertices = get_sphere('symmetric362').vertices
    tup = max_evecs.shape[:-1]
    mec = max_evecs.reshape(np.prod(np.array(tup)), 3)
    IN = np.array([np.argmin(np.dot(odf_vertices, m)) for m in mec])
    IN = IN.reshape(tup)
    return IN
 
common_fit_methods = {'WLS_DKI': wls_fit_dki,
                      'OLS_DKI' : ols_fit_dki,
                      'UWLLS_DKI': wls_fit_dki,
                      'ULLS_DKI' : ols_fit_dki
                      }