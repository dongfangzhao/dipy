
"""
==========================
Simple image visualization
==========================
"""
import numpy as np
import nibabel as nib
from dipy.data import fetch_sherbrooke_3shell, read_sherbrooke_3shell
from dipy.viz import window, actor
from dipy.core.histeq import histeq
from dipy.align.reslice import reslice

#fetch_sherbrooke_3shell()
#img, gtab = read_sherbrooke_3shell()


fraw = '/home/eleftherios/Data/MPI_Elef/fa_1x1x1.nii.gz'
fraw = '/home/eleftherios/Data/trento_processed/subj_01/MPRAGE_32/rawbet.nii.gz'
fraw = '/home/eleftherios/Data/trento_processed/subj_01/MPRAGE_32/T1_flirt_out.nii.gz'
# fraw = '/home/eleftherios/Data/Jorge_Rudas/tensor_fa.nii.gz'
img = nib.load(fraw)

# import nibabel as nib

data = img.get_data()
affine = img.get_affine()

affine = np.dot(np.diag([2., 2., 2., 1]), affine)

print(affine)
print(data.shape)

reslice = False

if reslice:
    zooms = img.get_header().get_zooms()[:3]
    new_zooms = (2, 2, 2.)
    data, affine = reslice(data, affine, zooms, new_zooms)

    print(affine)
    print(data.shape)

renderer = window.Renderer()

# S0 = data[..., 0]

vol = histeq(data)

world_coord = True
if world_coord:
    slice_actor = actor.slice(vol, affine)
else:
    slice_actor = actor.slice(vol)

renderer.add(slice_actor)

slice_actor2 = slice_actor.copy()

slice_actor2.display(slice_actor2.shape[0]/2, None, None)

renderer.background((1, 1, 1))

#renderer.add(slice_actor2)

window.show(renderer)