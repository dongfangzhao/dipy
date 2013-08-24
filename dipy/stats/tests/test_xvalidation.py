"""

Testing cross-validation analysis


"""
from __future__ import division, print_function, absolute_import
import numpy as np
import numpy.testing as npt
import nibabel as nib
import dipy.stats.xvalidation as xval
import dipy.stats.utils as ut
import dipy.data as dpd
import dipy.reconst.dti as dti
import dipy.core.gradients as gt
import dipy.sims.voxel as sims

def test_kfold_xval():
    """
    Test k-fold cross-validation
    """
    fdata, fbval, fbvec  = dpd.get_data('small_64D')
    data = nib.load(fdata).get_data()
    gtab = gt.gradient_table(fbval, fbvec)
    dm = dti.TensorModel(gtab, 'LS')
    # The data has 102 directions, so will not divide neatly into 10 bits
    npt.assert_raises(ValueError, xval.kfold_xval, dm, data, 10)

    psphere = dpd.get_sphere('symmetric362')
    bvecs = np.concatenate(([[0, 0, 0]], psphere.vertices))
    bvals = np.zeros(len(bvecs)) + 1000
    bvals[0] = 0
    gtab = gt.gradient_table(bvals, bvecs)
    mevals = np.array(([0.0015, 0.0003, 0.0001], [0.0015, 0.0003, 0.0003]))
    mevecs = [ np.array( [ [1, 0, 0], [0, 1, 0], [0, 0, 1] ] ),
               np.array( [ [0, 0, 1], [0, 1, 0], [1, 0, 0] ] ) ]
    S = sims.single_tensor( gtab, 100, mevals[0], mevecs[0], snr=None )

    dm = dti.TensorModel(gtab, 'LS')
    dmfit = dm.fit(S)

    kf_xval = xval.kfold_xval(dm, S, 2)
    cod = ut.coeff_of_determination(S[~gtab.b0s_mask], kf_xval)
    npt.assert_array_almost_equal(cod, np.ones(kf_xval.shape[:-1])*100)