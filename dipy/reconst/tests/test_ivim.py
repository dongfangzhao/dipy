""" Testing IVIM

"""
import numpy as np
from numpy.testing import (assert_array_equal, assert_array_almost_equal)

from dipy.reconst.ivim import ivim_function, IvimModel
from dipy.core.gradients import gradient_table
from dipy.sims.voxel import multi_tensor
from dipy.core.sphere import disperse_charges, HemiSphere


def test_nlls_fit():
    """
    Test the implementation of NLLS
    """
    bvals = np.array([0., 10., 20., 30., 40., 60., 80., 100.,
                      120., 140., 160., 180., 200., 220., 240.,
                      260., 280., 300., 350., 400., ])
    N = len(bvals)
    bvecs = get_bvecs(N)
    gtab = gradient_table(bvals, bvecs.T)

    S0, f, D_star, D = 1.0, 0.06, 0.0072, 0.00097

    mevals = np.array(([D_star, D_star, D_star], [D, D, D]))
    # This gives an isotropic signal

    signal = multi_tensor(gtab, mevals, snr=None, S0=S0, fractions=[
                          f * 100, 100 * (1 - f)])
    data = signal[0]
    ivim_model = IvimModel(gtab)
    ivim_fit = ivim_model.fit(data)

    est_signal = ivim_function(ivim_fit.model_params, bvals)

    assert_array_equal(est_signal.shape, data.shape)
    assert_array_almost_equal(est_signal, data)
    assert_array_almost_equal(ivim_fit.model_params, [S0, f, D_star, D])


def test_multivoxel():
    bvals = np.array([0., 10., 20., 30., 40., 60., 80., 100.,
                      120., 140., 160., 180., 200., 220., 240.,
                      260., 280., 300., 350., 400., ])
    N = len(bvals)
    bvecs = get_bvecs(N)
    gtab = gradient_table(bvals, bvecs.T)
    params = [[1.0, 0.06, 0.0072, 0.00097], [9.0, 0.05, 0.0074, 0.00087]]

    data = generate_multivoxel_data(gtab, params)
    ivim_model = IvimModel(gtab)

    guess_params = np.array([[1.0, 0.01, 0.001, 0.0009],
                             [0.9, 0.04, 0.002, 0.0004]])
    ivim_fit = ivim_model.fit(data)
    est_signal = generate_multivoxel_data(gtab, ivim_fit.model_params)

    assert_array_equal(est_signal.shape, data.shape)
    assert_array_almost_equal(est_signal, data)
    assert_array_almost_equal(ivim_fit.model_params, params)


def get_bvecs(N):
    """Generate bvectors for N bvalues"""
    theta = np.pi * np.random.rand(N)
    phi = 2 * np.pi * np.random.rand(N)
    hsph_initial = HemiSphere(theta=theta, phi=phi)
    hsph_updated, potential = disperse_charges(hsph_initial, 5000)
    vertices = hsph_updated.vertices
    return vertices


def generate_multivoxel_data(gtab, params):
    """Generate multivoxel data for testing"""
    data = []
    for parameters in params:
        S0, f, D_star, D = parameters
        mevals = np.array(([D_star, D_star, D_star], [D, D, D]))
        signal = multi_tensor(gtab, mevals, S0=S0, snr=None, fractions=[
            f * 100, 100 * (1 - f)])
        data.append(signal[0])
    return np.array(data)