import open3d
import os
import time
import numpy as np
import torch
from input_preparation import _ppf
from new_model import PPFFoldNet_new


def get_pcd(pcdpath, filename):
    return open3d.read_point_cloud(os.path.join(pcdpath, filename + '.ply'))


def get_keypts_desc(keyptspath, filename):
    keypts = np.fromfile(os.path.join(keyptspath, filename + '.keypts.bin'), dtype=np.float32)
    num_keypts = int(keypts[0])
    keypts = keypts[1:].reshape([num_keypts, 3])

    return keypts


def get_desc(filename):
    desc = np.fromfile(os.path.join(interpath, filename + '.desc.3dmatch.bin'), dtype=np.float32)
    num_desc = int(desc[0])
    desc_size = int(desc[1])
    desc = desc[2:].reshape([num_desc, desc_size])
    return desc


def build_ppf_input(pcd, keypts):
    kdtree = open3d.KDTreeFlann(pcd)
    keypts_id = []
    for i in range(keypts.shape[0]):
        _, id, _ = kdtree.search_knn_vector_3d(keypts[i], 1)
        keypts_id.append(id[0])
    neighbor = collect_local_neighbor(keypts_id, pcd, vicinity=0.3, num_points=1024)
    local_pachtes = build_local_patch(keypts_id, pcd, neighbor)
    return local_pachtes


def collect_local_neighbor(ids, pcd, vicinity=0.3, num_points=1024):
    kdtree = open3d.geometry.KDTreeFlann(pcd)
    res = []
    for id in ids:
        [k, idx, variant] = kdtree.search_radius_vector_3d(pcd.points[id], vicinity)
        # random select fix number [num_points] of points to form the local patch.
        if k > num_points:
            idx = np.random.choice(idx[1:], num_points, replace=False)
        else:
            idx = np.random.choice(idx[1:], num_points)
        res.append(idx)
    return np.array(res)


def build_local_patch(ref_inds, pcd, neighbor):
    open3d.geometry.estimate_normals(pcd)
    num_patches = len(ref_inds)
    num_points_per_patch = len(neighbor[0])
    # shape: num_ref_point, num_point_per_patch, 4
    local_patch = np.zeros([num_patches, num_points_per_patch, 4], dtype=float)
    for i, ref_ind, inds in zip(range(num_patches), ref_inds, neighbor):
        ppfs = _ppf(pcd.points[ref_ind], pcd.normals[ref_ind], np.asarray(pcd.points)[inds],
                    np.asarray(pcd.normals)[inds])
        local_patch[i] = ppfs
    return local_patch


def prepare_ppf_input(pcdpath, ppfpath, keyptspath):
    num_frag = len(os.listdir(pcdpath))
    num_ppf = len(os.listdir(ppfpath))
    if num_frag == num_ppf:
        print("PPF already prepared.")
        return
    for i in range(num_frag):
        filename = 'cloud_bin_' + str(i)
        pcd = get_pcd(pcdpath, filename)
        keypts = get_keypts_desc(keyptspath, filename)
        local_patches = build_ppf_input(pcd, keypts)  # [num_keypts, 1024, 4]
        np.save(ppfpath + filename + ".ppf.bin", local_patches.astype(np.float32))
        print("save", filename + '.ppf.bin')


def generate_descriptor(model, desc_name, pcdpath, ppfpath, ppfdescpath):
    model.eval()
    num_frag = len(os.listdir(pcdpath))
    for j in range(num_frag):
        local_patches = np.load(ppfpath + 'cloud_bin_' + str(j) + ".ppf.bin.npy")
        input_ = torch.tensor(local_patches)
        input_ = input_.cuda()
        model = model.cuda()
        # cuda out of memry
        desc_list = []
        for i in range(100):
            desc = model.encoder(input_[i * 50:(i + 1) * 50, :, :])
            desc_list.append(desc.detach().cpu().numpy())
            del desc
        desc = np.concatenate(desc_list, 0).reshape([5000, 512])
        np.save(ppfdescpath + 'cloud_bin_' + str(j) + f".desc.{desc_name}.bin", desc.astype(np.float32))


if __name__ == '__main__':
    scene_list = [
        '7-scenes-redkitchen',
        'sun3d-home_at-home_at_scan1_2013_jan_1',
        'sun3d-home_md-home_md_scan9_2012_sep_30',
        'sun3d-hotel_uc-scan3',
        'sun3d-hotel_umd-maryland_hotel1',
        'sun3d-hotel_umd-maryland_hotel3',
        'sun3d-mit_76_studyroom-76-1studyroom2',
        'sun3d-mit_lab_hj-lab_hj_tea_nov_2_2012_scan1_erika'
    ]
    # datapath = "./data/test/sun3d-hotel_umd-maryland_hotel3/"
    # interpath = "./data/intermediate-files-real/sun3d-hotel_umd-maryland_hotel3/"
    # savepath = "./data/intermediate-files-real/sun3d-hotel_umd-maryland_hotel3/"
    for scene in scene_list:
        pcdpath = f"/data/3DMatch/fragments/{scene}/"
        interpath = f"/data/3DMatch/intermediate-files-real/{scene}/"
        keyptspath = os.path.join(interpath, "keypoints/")
        ppfpath = os.path.join(interpath, "ppf/")
        ppfdescpath = os.path.join(interpath, "ppf_desc/")
        model = PPFFoldNet_new(100, 1024)
        model.load_state_dict(torch.load('/home/xybai/PPF-FoldNet/snapshot/PPF-FoldNet04170839/models/sun3d_best.pkl'))
        start_time = time.time()
        print(f"Begin prepare ppf input for {scene}")
        prepare_ppf_input(pcdpath=pcdpath, ppfpath=ppfpath, keyptspath=keyptspath)
        print(f"Finish in {time.time() - start_time}")
        start_time = time.time()
        print(f"Begin Processing {scene}")
        generate_descriptor(model, desc_name='ppf', pcdpath=pcdpath, ppfpath=ppfpath, ppfdescpath=ppfdescpath)
        print(f"Finish in {time.time() - start_time}s")
