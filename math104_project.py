# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.utils import shuffle
from sklearn.metrics import classification_report, confusion_matrix
from tqdm import tqdm
import os
import random

from tensorflow import keras
from keras.layers import *
from keras.losses import *
from keras.models import *
from keras.metrics import *
from tensorflow.python.keras import optimizers
from tensorflow.keras.preprocessing.image import load_img

curr_dir = os.getcwd() + "/drive/MyDrive/math104_project"
np.random.seed(42)
train_dir = curr_dir + "/Training"
test_dir = curr_dir + "/Testing"

train_paths = []
test_paths = []
train_labels = []
test_labels = []

# Either glioma or no tumor 
for label in os.listdir(train_dir):
    if not label.startswith('.'):
        for image in os.listdir(train_dir + '/' + label):
          if not image.startswith('.'):
              train_paths.append(train_dir + '/' + label + '/'+ image)
              train_labels.append(label)

for label in os.listdir(test_dir):
    if not label.startswith('.'):
        for image in os.listdir(test_dir + '/' + label):
          if not image.startswith('.'):
              test_paths.append(test_dir + '/' + label + '/'+ image)
              test_labels.append(label)

test_paths, test_labels = shuffle(test_paths, test_labels)
train_paths, train_labels = shuffle(train_paths, train_labels)

#Step 1: Resize and augment images
def resize_and_augment(image):
    new_size = (128, 128)
    new_shape = (128, 128, 3)
    image = Image.fromarray(np.uint8(image))
    image = ImageEnhance.Brightness(image).enhance(np.random.uniform(0.7,1.3))
    image = ImageEnhance.Contrast(image).enhance(np.random.uniform(0.7, 1.3))
    image = image.resize(new_size)
    image = np.array(image)/ 255.0
    image = np.reshape(image, new_shape)
    return image

# Visualize sample of no tumor MRIs and gliomas before compression
def open_img(paths, compressed = False, savings = 0.6):
    imgs = []
    for path in paths:
        image = load_img(path, target_size=(256,256))
        image = resize_and_augment(image)
        if compressed:
          image, _ = compress_img(image, savings)
        imgs.append(image)
    return np.array(imgs)
  
images = open_img(train_paths[10:19])
labels = train_labels[10:19]
fig = plt.figure(figsize=(12, 6))
for idx in range(1, 9):
    fig.add_subplot(2, 4, idx)
    plt.axis('off')
    plt.title(labels[idx])
    plt.imshow(images[idx])
plt.rcParams.update({'font.size': 12})
plt.show()

#Step 2: Perform compression on each channel of the images w/ storage savings maximization

def calc_svd(img, full_matrix=False):
    U, D, V_T = np.linalg.svd(img, full_matrices=full_matrix)
    return (U, np.diag(D), V_T)


def space_savings(rank, n_rows, n_cols):
    original_space = n_rows * n_cols
    compressed_space = n_rows * rank + rank + n_cols * rank #From SVD
    return 1 - float(compressed_space / original_space)

#Identify optimal rank of SVD to maximize compression
def calc_optimal_rank(X, savings):
     _, D, _ = calc_svd(X)
     max_rank = D.shape[0]
     best_rank = 1
     while True:
        curr_savings = space_savings(best_rank, D.shape[0], D.shape[1])
        if curr_savings > savings:
            best_rank += 1
            continue
        # Reduce rank by 1 then break
        if curr_savings < savings:
            best_rank -= 1
            break
     return best_rank 

def compress_img(img, savings):
    compressed_image = np.zeros_like(img)
    perc_savings_total = 0
    for channel in range(3):
      best_rank = calc_optimal_rank(img[:,:,channel], savings)
      U, D, V_T = calc_svd(img[:,:,channel])
      compressed_image[:,:,channel] = U[:, :best_rank] @ D[:best_rank, :best_rank] @ V_T[:best_rank, :]
      perc_savings_total += space_savings(best_rank, 128, 128)
    perc_savings = perc_savings_total / 3
    return compressed_image, perc_savings

# Plot rank vs space savings for a single value
img = open_img([train_paths[56]]).reshape((128, 128, 3))
label = train_labels[56]

ranks = [5, 20, 50, 75, 100]
fig = plt.figure(0, (18, 12))
fig.subplots_adjust(top=1.1)

# Get low rank approximation over each channel
for idx, rank in enumerate(ranks):
    X_r = np.zeros_like(img)
    for channel in range(3):
      U, D, V_T = calc_svd(img[:,:, channel])
      X_r[:, :, channel] = U[:, :rank] @ D[:rank, :rank] @ V_T[:rank, :]

    ax = plt.subplot(2,3, idx + 1)
    ax.imshow(X_r, cmap='gray')
    ax.set_xticks([])
    ax.set_yticks([])

    ax.set_title(f"rank {rank}\nspace savings: {100 * (space_savings(rank, img.shape[0], img.shape[1]))}%")
    
ax = plt.subplot(2, 3, idx + 2)
ax.imshow(img, cmap='gray')
ax.set_title(f"original image with {label}")
ax.set_xticks([])
ax.set_yticks([])

#Step 3: Train Vgg19 performance on the before and after datasets

# Create data generator
unique_labels = os.listdir(train_dir)
unique_labels.remove('.DS_Store')

def encode_label(labels):
    encoded = []
    for label in labels:
        if unique_labels.index(label) == -1:
          print("something's wrong")
        encoded.append(unique_labels.index(label))
    return np.array(encoded)

def decode_label(labels):
    decoded = []
    for label in labels:
        decoded.append(unique_labels[label])
    return np.array(decoded)

def datagen(paths, labels, batch_size=16, epochs=1, compressed = False):
    for _ in range(epochs):
        for idx in range(0, len(paths), batch_size):
            batch_paths = paths[idx: idx + batch_size]
            # 30% space savings
            batch_images = open_img(batch_paths, compressed = compressed, savings = 0.4)
            batch_labels = labels[idx: idx + batch_size]
            batch_labels = encode_label(batch_labels).reshape(-1,1)
            yield batch_images, batch_labels

#Set up model
base_model = tf.keras.applications.vgg19.VGG19(input_shape=(128,128,3), include_top=False, weights='imagenet')
# Set all layers to non-trainable but last block
for layer in base_model.layers:
    layer.trainable = False
base_model.layers[-2].trainable = True
base_model.layers[-3].trainable = True
base_model.layers[-4].trainable = True

model = Sequential()
model.add(Input(shape=(128,128,3)))
model.add(base_model)
model.add(Flatten())
model.add(Dropout(0.3))
model.add(Dense(256, activation='relu'))
model.add(Dropout(0.2))
model.add(Dense(len(unique_labels), activation='sigmoid'))
model.summary()

model.compile(optimizer = "Adam", loss="binary_crossentropy", metrics = [tf.keras.metrics.BinaryAccuracy(name="binary_accuracy")])

# Train model on the uncompressed data + plot training statistics
batch_size = 20
steps = len(train_paths)// batch_size
epochs = 4
history_uncompressed = model.fit(datagen(train_paths, train_labels, batch_size=batch_size, epochs = epochs),
                    epochs=epochs, steps_per_epoch=steps)

plt.figure(figsize=(8,4))
plt.grid(True)
plt.plot(history_uncompressed.history['binary_accuracy'], '.g-', linewidth=2)
plt.plot(history_uncompressed.history['loss'], '.r-', linewidth=2)
plt.title('Uncompressed Model Training History')
plt.xlabel('epoch')
plt.xticks([x for x in range(epochs)])
plt.legend(['Accuracy', 'Loss'], loc='upper left', bbox_to_anchor=(1, 1))
plt.show()

# Train model on the compressed data
batch_size = 20
epochs = 5
steps = len(train_paths)// batch_size

model_compressed = tf.keras.models.clone_model(model)
model_compressed.summary()
model_compressed.compile(optimizer = "Adam", loss="binary_crossentropy", metrics = [tf.keras.metrics.BinaryAccuracy(name="binary_accuracy")])
history_compressed = model_compressed.fit(datagen(train_paths, train_labels, batch_size=batch_size, epochs=epochs, compressed = True),
                    epochs=epochs, steps_per_epoch=steps)

plt.figure(figsize=(8,4))
plt.grid(True)
plt.plot(history_compressed.history['binary_accuracy'], '.g-', linewidth=2)
plt.plot(history_compressed.history['loss'], '.r-', linewidth=2)
plt.title('Compressed Model Training History')
plt.xlabel('epoch')
plt.xticks([x for x in range(epochs)])
plt.legend(['Accuracy', 'Loss'], loc='upper left', bbox_to_anchor=(1, 1))
plt.show()

#Step 4: Test model to see how different classification accuracy is 
batch_size = 32
steps = len(test_paths)// batch_size
y_pred_uncompressed = []
y_true_uncompressed = []
y_pred_compressed = []
y_true_compressed = []
idx = 0
for x,y in tqdm(datagen(test_paths, test_labels, batch_size=batch_size, epochs=1, compressed = False), total=steps):
    pred = model.predict(x)
    pred = np.argmax(pred, axis=-1)
    for i in decode_label(y.flatten()):
        y_true_uncompressed.append(i)
    for i in decode_label(pred):
        y_pred_uncompressed.append(i)
    
for x,y in tqdm(datagen(test_paths, test_labels, batch_size=batch_size, epochs=1, compressed = True), total=steps):
    pred_compressed = model_compressed.predict(x)
    pred_compressed = np.argmax(pred_compressed, axis=-1)
    for i in decode_label(y.flatten()):
        y_true_compressed.append(i)
    for i in decode_label(pred_compressed):
        y_pred_compressed.append(i)

print(classification_report(y_true_uncompressed, y_pred_uncompressed))

print(classification_report(y_true_compressed, y_pred_compressed))

# Plot confusion matrix for each together
compress_confusion = confusion_matrix(y_true_compressed, y_pred_compressed)
uncompress_confusion = confusion_matrix(y_true_uncompressed, y_pred_uncompressed)
fig, (ax1, ax2) = plt.subplots(1, 2)
fig.set_size_inches(12, 6)
sns.heatmap(compress_confusion, annot=True, fmt='g', ax=ax1)

# labels, title and ticks
ax1.set_xlabel('Predicted labels')
ax.set_ylabel('True labels')
ax1.set_title('Compressed Confusion Matrix')
ax1.xaxis.set_ticklabels(['notumor', 'glioma'])
ax1.yaxis.set_ticklabels(['notumor', 'glioma'])

sns.heatmap(uncompress_confusion, annot=True, fmt='g', ax=ax2)

# labels, title and ticks
ax2.set_xlabel('Predicted labels');ax.set_ylabel('True labels')
ax2.set_title('Uncompressed Confusion Matrix')
ax2.xaxis.set_ticklabels(['notumor', 'glioma'])
ax2.yaxis.set_ticklabels(['notumor', 'glioma'])
