import os
import re
import sys
import json
import time
import cv2
import argparse
import numpy as np
from utils import load_options
from utils import to_labels_array, to_labels_dict
from video_loader import MultipleVideoLoader
from is_wire.core import Logger
from collections import OrderedDict

from is_msgs.image_pb2 import ObjectAnnotations
from is_msgs.image_pb2 import HumanKeypoints as HKP
from google.protobuf.json_format import ParseDict
from itertools import permutations

colors = list(permutations([0, 255, 85, 170], 3))
links = [(HKP.Value('HEAD'), HKP.Value('NECK')),
         (HKP.Value('NECK'), HKP.Value('CHEST')),
         (HKP.Value('CHEST'), HKP.Value('RIGHT_HIP')),
         (HKP.Value('CHEST'), HKP.Value('LEFT_HIP')),
         (HKP.Value('NECK'), HKP.Value('LEFT_SHOULDER')),
         (HKP.Value('LEFT_SHOULDER'), HKP.Value('LEFT_ELBOW')),
         (HKP.Value('LEFT_ELBOW'), HKP.Value('LEFT_WRIST')),
         (HKP.Value('NECK'), HKP.Value('LEFT_HIP')),
         (HKP.Value('LEFT_HIP'), HKP.Value('LEFT_KNEE')),
         (HKP.Value('LEFT_KNEE'), HKP.Value('LEFT_ANKLE')),
         (HKP.Value('NECK'), HKP.Value('RIGHT_SHOULDER')),
         (HKP.Value('RIGHT_SHOULDER'), HKP.Value('RIGHT_ELBOW')),
         (HKP.Value('RIGHT_ELBOW'), HKP.Value('RIGHT_WRIST')),
         (HKP.Value('NECK'), HKP.Value('RIGHT_HIP')),
         (HKP.Value('RIGHT_HIP'), HKP.Value('RIGHT_KNEE')),
         (HKP.Value('RIGHT_KNEE'), HKP.Value('RIGHT_ANKLE')),
         (HKP.Value('NOSE'), HKP.Value('LEFT_EYE')),
         (HKP.Value('LEFT_EYE'), HKP.Value('LEFT_EAR')),
         (HKP.Value('NOSE'), HKP.Value('RIGHT_EYE')),
         (HKP.Value('RIGHT_EYE'), HKP.Value('RIGHT_EAR'))]


def render_skeletons(images, annotations, it, colors, links):
    """_summary_

    Args:
        images (_type_): _description_
        annotations (_type_): _description_
        it (_type_): _description_
        colors (_type_): _description_
        links (_type_): _description_
    """

    # O que esse loop faz
    for cam_id, image in images.items():
        skeletons = ParseDict(annotations[cam_id][it], ObjectAnnotations())
        for ob in skeletons.objects:
            parts = {}
            for part in ob.keypoints:
                parts[part.id] = (int(part.position.x), int(part.position.y))
            for link_parts, color in zip(links, colors):
                begin, end = link_parts
                if begin in parts and end in parts:
                    cv2.line(
                        image,
                        parts[begin],
                        parts[end],
                        color=color,
                        thickness=4)
            for center in parts.values():
                cv2.circle(
                    image,
                    center=center,
                    radius=4,
                    color=(255, 255, 255),
                    thickness=-1)


def place_images(output_image, images, x_offset=0, y_offset=0):
    """_summary_

    Args:
        output_image (_type_): _description_
        images (_type_): _description_
        x_offset (int, optional): _description_. Defaults to 0.
        y_offset (int, optional): _description_. Defaults to 0.
    """
    w, h = images[0].shape[1], images[0].shape[0]
    output_image[0 + y_offset:h + y_offset, 0 + x_offset:w +
                 x_offset, :] = images[0]

    output_image[0 + y_offset:h + y_offset, w + x_offset:2 * w +
                 x_offset, :] = images[1]

    output_image[h + y_offset:2 * h + y_offset, 0 + x_offset:w +
                 x_offset, :] = images[2]

    output_image[h + y_offset:2 * h + y_offset, w + x_offset:2 * w +
                 x_offset, :] = images[3]


log = Logger(name='WatchVideos')

#??
with open('keymap.json', 'r') as f:
    keymap = json.load(f)
options = load_options(print_options=False)

if not os.path.exists(options.folder):
    log.critical("Folder '{}' doesn't exist", options.folder)

with open('gestures.json') as f:
    gestures = json.load(f)
    #Ordered de sorted?
    gestures = OrderedDict(sorted(gestures.items(), key=lambda kv: int(kv[0])))

parser = argparse.ArgumentParser(
    description='Utility to capture a sequence of images from multiples cameras'
)

#O que sao gestures?
parser.add_argument(
    '--person', '-p', type=int, required=True, help='ID to identity person')
parser.add_argument(
    '--gesture', '-g', type=int, required=True, help='ID to identity gesture')
args = parser.parse_args()

person_id = args.person
gesture_id = args.gesture

if str(gesture_id) not in gestures:
    log.critical("Invalid GESTURE_ID: {}. \nAvailable gestures: {}",
                 gesture_id, json.dumps(gestures, indent=2))

if person_id < 1 or person_id > 999:
    log.critical("Invalid PERSON_ID: {}. Must be between 1 and 999.",
                 person_id)

log.info("PERSON_ID: {} GESTURE_ID: {}", person_id, gesture_id)

cameras = [int(cam_config.id) for cam_config in options.cameras]

video_files = {
    cam_id: os.path.join(
        options.folder, 'p{:03d}g{:02d}c{:02d}.mp4'.format(
            person_id, gesture_id, cam_id))
    for cam_id in cameras
}

json_files = {
    cam_id: os.path.join(
        options.folder, 'p{:03d}g{:02d}c{:02d}_2d.json'.format(
            person_id, gesture_id, cam_id))
    for cam_id in cameras
}

if not all(
        map(os.path.exists,
            list(video_files.values()) + list(json_files.values()))):
    log.critical(
        'Missing one of video or annotations files from PERSON_ID {} and GESTURE_ID {}',
        person_id, gesture_id)

size = (2 * options.cameras[0].config.image.resolution.height,
        2 * options.cameras[0].config.image.resolution.width,
        3)
full_image = np.zeros(size, dtype=np.uint8)

video_loader = MultipleVideoLoader(video_files)

# load annotations
annotations = {}
for cam_id, filename in json_files.items():
    with open(filename, 'r') as f:
        annotations[cam_id] = json.load(f)['annotations']

fourcc = cv2.VideoWriter_fourcc(*'XVID')
fps = 7.0
resolution = (1288, 728)
outlist = [cv2.VideoWriter(
    f'cam{i}.avi', fourcc, fps, resolution) for i in range(4)]
'''out0 = 
out1 = cv2.VideoWriter('cam1.avi', fourcc, fps, resolution)
out2 = cv2.VideoWriter('cam2.avi', fourcc, fps, resolution)
out3 = cv2.VideoWriter('cam3.avi', fourcc, fps, resolution)'''

update_image = True
it_frames = 0
while True:
    n_loaded_frames = video_loader.load_next()
    frames = video_loader[it_frames]
    if frames is None:
        break

    render_skeletons(frames, annotations, it_frames, colors, links)
    frames_list = [frames[cam] for cam in sorted(frames.keys())]
    it_frames += 1

    for i in range(len(outlist)):
        outlist[i].write(frames_list[i])

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

for i in range(len(outlist)):
    outlist[i].release()
log.info('Exiting')
