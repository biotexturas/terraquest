# head_tracking (drive id 1R7CPiBZ8hYzHRmksvGtL9eTM_EId3VAp)

## cell 0 [markdown]
# Swarming ArrowHead Tracking

## cell 1 [markdown]
Provided we have a timelapse of [Paenibacillus](https://en.wikipedia.org/wiki/Paenibacillus) or other swarming bacteria we can use this code
*locate* and *track* (?) their **ArrowHeads**. ArrowHeads are a particular type of [Swarming](https://en.wikipedia.org/wiki/Swarm_behaviour) morphological structure which act as macroscopic propagules searching for new territory.

## cell 2 [markdown]
We first **import five modules** we will need into the `Python3` environment

## cell 3 [code]
```python
# import OpenCV module  (Computer Vision)
import cv2 as cv

# import PyPlot module from MatPlotLib (Plotting Images)
import matplotlib.pyplot as plt

# import Numerical Python module (Numerical arrays)
import numpy as np

# import a function to calculate functions on/of images (Structural Similarity)
# in older version the function was in skimage.measure and was called "compare_ssim"
from skimage.metrics import structural_similarity

# import a module to manipulate Unix-like file PATH structures in the file system (PATH Unix-like)
from glob import glob
```

## cell 4 [markdown]
First we difine some **point** which is to represent the location of our point of interest.

## cell 5 [code]
```python
# previous center (centroid of a contour) position
pcx = 0
pcy = 0
```

## cell 6 [markdown]
We **load** two files pointing to **two consecutive images** of a *timelapse* `data` stored in the local `filesystem`. We use the `glob` module to deal with the `filesystem` and `cv2` module to load the images into `memory` using the `imread` function

## cell 7 [code]
```python
path_to_images = glob("/home/juan/code/Python/Paenibacillus_tracking/pictures_ArrowHead/*.jpg")
```

## cell 8 [code]
```python
path_to_images = sorted(path_to_images)
```

## cell 9 [code]
```python
nameA = path_to_images[0]
nameB = path_to_images[1]

imageA = cv.imread(nameA)
imageB = cv.imread(nameB)
```

## cell 10 [markdown]
Running the code above (all cells) we have two consecutive frames (10 minutes appart in our data) of a **moving ArrowHead**. We can **plot** these two images using `matplotlib.pyplot`' functions `subplots` and `imshow`

## cell 11 [code]
```python
%matplotlib inline
```

## cell 12 [code]
```python
figure, axis_array = plt.subplots(1,2)
axis_array[0].imshow(imageA)
axis_array[1].imshow(imageB)
```

## cell 13 [markdown]
Once we have these two images in `memory` we can do some **image manipulation** and then some **analysis**. We notice, by inspecting their `shape`, that these images have 2464 pixels of `height` and 3280 of `width` and they are of `depth` 3. These are BGR (Blue Green Red) images where each of these 3 color fields have values running fom `0 to 255` integer values if the `color depth` is `8 bit`.

## cell 14 [code]
```python
imageA.shape
```

## cell 15 [markdown]
Using `cv2`, we **transform** (convert) both images to **gray** scale. We use `cvtColor` function for this.

## cell 16 [code]
```python
grayA = cv.cvtColor(imageA, cv.COLOR_BGR2GRAY)
grayB = cv.cvtColor(imageB, cv.COLOR_BGR2GRAY)
```

## cell 17 [markdown]
So now The images' `depth` will be a single `real number` value of light intensity `from 0 to 1`

## cell 18 [markdown]
grayA.shape

## cell 19 [markdown]
Then, using `cv2` again, we **blur** (clean) the images to remove high frequency fluctuations (low pass filter). for this operationn we usde the module's function `GaussianBlur` with a *kernel* of size (101,101) pixels.

## cell 20 [code]
```python
cleanA = cv.GaussianBlur(grayA, (101,101), 0)
cleanB = cv.GaussianBlur(grayB, (101,101), 0)
```

## cell 21 [markdown]
Using the function `structural_similarity` **SSIM** from the `skimage.metrics` module so we can compare the [structural similarity](https://en.wikipedia.org/wiki/Structural_similarity_index_measure) between the two images

## cell 22 [code]
```python
(score, diff) = structural_similarity(cleanA, cleanB, full= True)
```

## cell 23 [markdown]
We get a **good score** with the chosen kernel for these particular images

## cell 24 [code]
```python
score
```

## cell 25 [markdown]
So the (gray scale) image obtained show the most stricking *feature* charaterizing the difference between the two. Namely, the advancement of the **ArrowHead's front** from one frame to the next. We plot it using the `imshow`function of `matplotlib.pyplot`

## cell 26 [code]
```python
# lets re-scale the gray image (real 0-1) to make it 8-bits (integer 0-255) in depth uint8 
scaled_diff = (diff * 255).astype("uint8")
# once re-scaled, we plot
plt.imshow(scaled_diff)
```

## cell 27 [markdown]
To make this feature more clear, using the `threshold` function of `cv2`, we threshold the image and **convert it to a binary image** (*thresh*). Of the tree types of thresholding we use the Otsu thresholding method to automatically obtain the *threshold value* (*T*) from the pixel intensity distribution (assumed to be bi-modal by the **Otsu method**)

## cell 28 [code]
```python
(T,thresh) = cv.threshold(scaled_diff, 0, 255, cv.THRESH_BINARY_INV | cv.THRESH_OTSU)
# the calculated threshold is:
T

```

## cell 29 [code]
```python
# and the binary image produced is
plt.imshow(thresh)
```

## cell 30 [markdown]
Now we want to calculate all the [contours](https://medium.com/featurepreneur/draw-contours-on-an-image-using-opencv-186b67f87c92) of this image using the `findContours` function of `CV2`

## cell 31 [code]
```python
(contours, hierarchy) = cv.findContours(thresh.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
```

## cell 32 [code]
```python
print(f"The function above finds {len(contours)} contours")
```

## cell 33 [code]
```python
for i in range (0 , len(contours)):
    print(f"contour {i}:  \t{len(contours[i])} \t points")
```

## cell 34 [markdown]
A simple **guess** (happens to be the one with more points) we guess **contour number 3**

## cell 35 [code]
```python
image = imageB.copy()
#image = cv.drawContours(image, contours, -1, (255, 0, 0), 25) 
image = cv.drawContours(image, contours, 3, (255, 0, 0), 25)
plt.imshow(image)
```

## cell 36 [markdown]
Lets define a criteria to find contour 3 among the 11. For this, we can use [contour feautures](https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html) (like its **moments**) to define its **centroid**.

## cell 37 [code]
```python
# to store the centroid of each contour we make a couple of arrays of coordinates
x_list = np.zeros(len(contours))
y_list = np.zeros(len(contours))
```

## cell 38 [code]
```python
# we also store a value (criteria) for each contour
criteria = np.zeros(len(contours)) #.astype(np.longdouble)
```

## cell 39 [code]
```python
for i in range (0 , len(contours)):
    contour = contours[i]
    M = cv.moments(contour)
    area = M['m00']
    #print(area)
    if area == 0:
        criteria[i] = 0
    else:
        cx = int(M['m10']/area)
        cy = int(M['m01']/area)
        x_list[i] = cx
        y_list[i] = cy
        distance = (cx - pcx)**2 + (cy - pcy)**2
        if distance == 0:
            criteria[i]=0
        else:
            criteria[i] = np.exp(0.001*area)/distance
            
```

## cell 40 [code]
```python
#print(criteria)
```

## cell 41 [code]
```python
print(f"contour: {np.argmax(criteria)} \t is best: {criteria[np.argmax(criteria)]}")
```

## cell 42 [code]
```python
contour =  contours[np.argmax(criteria)]
```

## cell 43 [code]
```python
M = cv.moments(contour)
```

## cell 44 [code]
```python
M
```

## cell 45 [code]
```python
c = int(np.argmax(criteria)) 
c
```

## cell 46 [code]
```python
image = cv.circle(image,(int(x_list[c]),int(y_list[c])),25, (0, 255, 0),-1)

```

## cell 47 [code]
```python
plt.imshow(image)
```

## cell 48 [code]
```python

```
