# clusters (drive id 1aNLtBpqRjXJrNj2i37jSZg_wtsg9_KXz)

## cell 0 [markdown]
# Pablo's Optical Flow Clusters

## cell 1 [markdown]
In this Notebook we play with Pablo (Bravo)'s code to make a cluster analysis of [Paenibacillus](https://en.wikipedia.org/wiki/Paenibacillus) Optical Flow patterns.
As Pablo points out, three images are needed. Two for the Optical Flow and another one for denoising.

## cell 2 [markdown]
We first **import four modules** we will need into the `Python3` environment

## cell 3 [code]
```python
# import OpenCV module  (Computer Vision)
import cv2 as cv

# import PyPlot module from MatPlotLib (Plotting Images)
import matplotlib.pyplot as plt

# import Numerical Python module (Numerical arrays)
import numpy as np

# import a module to manipulate Unix-like file PATH structures in the file system (PATH Unix-like)
from glob import *
```

## cell 4 [markdown]
We start by encapsulating all the **Optical Flow calculations** to a sigle function `find_flow()`

## cell 5 [code]
```python
def find_flow(folder, n, res, win, levels):
    # Parameters are:
    # 1. the folder with jpg files with frames,
    # 2. the picture n to consider as the reference frame
    # 3. the number of grid points (red) to use (resolution)
    # 4. the size of the window (win) used for the flow calculation
    # 5. the number of levels (levels) for the image pyramids
    # The function finds the flow between two frames: {n , n +1}
    # Returns: 
    # a. the original image in gray scale and 
    # b. a 2D matrix Pablo defined which needs to be decifered
    # c. a list of vectors
    # We store the path to the sampled images
    in_fns = glob(folder + "*.jpg") # Names of files
    in_fns = sorted(in_fns)  # Order them
    old_frame = cv.imread(in_fns[n],cv.IMREAD_UNCHANGED) # Load
    old_gray = cv.cvtColor(old_frame,cv.COLOR_BGR2GRAY) # Gray
    h ,w , c = old_frame.shape   # dimensions
    pts = []                     # List of grid points to analyze
    for i in range (0 , w , res ):
        for j in range (0 , h , res ):
            pts . append ([[ i , j ]])
    p0 = np.array (pts , dtype = "float32")
    lk_params = dict(winSize = (win, win), # contrary to Interpecifics Pablo uses window of size 10
                    maxLevel = levels,    # contrary to Interspecifics, Pablo uses 10 levels
                    criteria = (cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 10 , 0.03))
    # Now we load a new frame as we also need a second image taken immediatly after
    frame = cv.imread(in_fns[n+1],cv.IMREAD_UNCHANGED)  # Load
    frame_gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)  # Gray
    # Now we actually calculate the Flow using the Library's function
    p1, status, err = cv.calcOpticalFlowPyrLK(old_gray, frame_gray, p0, None, **lk_params)
    # We filter and consider only those points that regustered flow movement
    good_new = p1[status == 1]
    good_old = p0[status == 1]
    # We create a list to store the flow vectors
    vectors = []
    # We loop over all the "good" vectors obtained
    for i, (new,old) in enumerate(zip(good_new,good_old)):
        a,b = new.ravel()
        c,d = old.ravel()
        vectors.append(np.array([a, b, c, d])) # Append vector
    # original image in gray scale
    img = frame_gray
    # We now map the list of flow vectors to a 2D array
    V = np.zeros([int(np.ceil(h/res)), int(np.ceil(w/res)), 2])
    for v in vectors:
        i,j = int(v[3]/res), int(v[2]/res)
        V[i,j] = np.array(v[1],v[0])
    # return
    return img, V, vectors
```

## cell 6 [markdown]
The to get Optical Flow we just call (Pablo uses 10 and 10 while interspecifics 15, and 4 for win and levels respectively)

## cell 7 [code]
```python
img, V, vectors = find_flow("./pictures_Saturns/", 0, 50, 15, 4)
#img, V, vectors = find_flow("./pictures_Saturns/", 0, 10, 10, 4)
```

## cell 8 [code]
```python
vfield = np.zeros_like(img)
```

## cell 9 [code]
```python
V.shape
```

## cell 10 [code]
```python
V[2,1,1]
```

## cell 11 [code]
```python
vectors
```

## cell 12 [code]
```python
vectors[0][1]
```

## cell 13 [code]
```python
V[1,0,:]
```

## cell 14 [code]
```python
%matplotlib inline
```

## cell 15 [code]
```python
plt.imshow(img)
```

## cell 16 [markdown]
A la interspecifics we can make the field from vectors

## cell 17 [code]
```python
i = 0
for v in vectors:
    cv.arrowedLine(vfield, (int(vectors[i][0]),int(vectors[i][1])), (int(vectors[i][2]),int(vectors[i][3])), (127,125,125), 10)
    i = i + 1
```

## cell 18 [code]
```python
plt.imshow(vfield)
```

## cell 19 [code]
```python
img_w_flow= cv.add(img, vfield)
```

## cell 20 [code]
```python
plt.imshow(img_w_flow)
```

## cell 21 [code]
```python
V.shape[1]
```

## cell 22 [markdown]
**To do**: Can we do the same but using V matrix instead? what is the difference?

## cell 23 [markdown]
Now we define a function to **split the Optical Flow** vectors into 2 components: 
(i) **direction** and (ii) **magnitude**

## cell 24 [code]
```python
def get_angle(V, res, vmin, vmax):
        # Splits Optical Flow vectors on two matrices
        # Angle matrix and Velocity (magnitude) matrix
    # Velocity Magniture matrix
    V_mag = np.zeros([V.shape[0], V.shape[1]])
    # Angle Matrix
    Angle = np.zeros([V.shape[0], V.shape[1]])

    # Create 2D VMag array
    for i in range(V_mag.shape[0]):
        for j in range(V_mag.shape[1]):
            mag = np.linalg.norm([V[i,j,0] - res*i, V[i,j,1] - res*j]) 
            if(vmin <= mag <= vmax):
                V_mag[i,j] = mag
    
    # Create 2D Angle array
    for i in range(V_mag.shape[0]):
        for j in range(V_mag.shape[1]):
            if(vmin <= V_mag[i,j] <= vmax):
                Angle[i,j] = np.arctan2(V[i,j,0] - res*i, V[i,j,1] - res*j)
            else:
                Angle[i,j] = np.NaN
    
    return Angle, V_mag

                                        
```

## cell 25 [code]
```python
Angle, V_mag = get_angle (V , 0 , 0 , 400 )
```

## cell 26 [code]
```python
Angle.shape
```

## cell 27 [code]
```python
plt.imshow(V_mag)
```

## cell 28 [markdown]
**Angle Difference** function

## cell 29 [code]
```python
def ang_dif(a,b):
    # Returns the magnitude of the difference between 2 angles
    L = 2* np.pi
    t1 = np.array([b-a, b - a - np.sign(b-a)*L])
    i1 = np.array(np.fabs(t1))
    return np.linalg.norm(t1[i1])

```

## cell 30 [markdown]
**Find Index** function

## cell 31 [code]
```python
def find_index(A,x):
    # Returns all the indeces in A with value x
    coords = np.where(A == x)
    list_of_coords = list(zip(coords[0], coords[1]))
    return list_of_coords

```

## cell 32 [markdown]
**Replace** function (note scope of A here?)

## cell 33 [code]
```python
def replace(A, x, y):
    # Replaces all the values x in array A for value y
    l = find_index(A, x)
    for i in l:
        A[i] = y
```

## cell 34 [markdown]
**Neighbors** function

## cell 35 [code]
```python
def float_range_neighbors(A, C, r, theta, i, j):
    # Returns neighbors for a given cell {i,j} on matrix A
    # Neighbors are given on matrix A (original) and C (clustered)
    # Parameters are {r, theta}
    Lx, Ly = A.shape[0], A.shape[1]
    N = []
    for x in range(np.max([i-r, 0]), np.min([i+r+1, Lx])):
        for y in range(np.max([j-r, 0]), np.min([j+r+1, Ly])):
            if C[x,y] != 0: # If neiighbors are alrady clustered
                if ang_dif(A[x,y], A[i,j]) < theta: # If angles are similar
                    N.append(C[x,y])  # If all tests passed
    return np.array(N)
```

## cell 36 [markdown]
**Non-immediate neighbors**

## cell 37 [code]
```python
def float_range_hk(A, r, theta):
    # Returns clusters with non-inmediate neighbors
    largest_label = 1
    C = np.zeros([A.shape[0], A.shape[1]], float) # track all clusters
    for i in range(A.shape[0]):                   # loop over matrix
        for j in range(A.shape[1]):
            if not np.isnan(A[i,j]):              # if cell has a value
                N = float_range_neighbors(A, C, r, theta, i, j) # get all neighbors 
                if  len(N) == 0:                  # if there are no neighbors
                    C[i,j] = largest_label
                    largest_label +=1
                else:
                    C_vals = np.unique(N)
                    C_max  = np.max(C_vals)
                    for cvalues in C_vals:
                        replace(C,cvals, C_max)
                    C[i,j] =  C_max
    return C

                    
        
```

## cell 38 [markdown]
**Big cluster** function

## cell 39 [code]
```python
def big_clusters(A_copy, n):
    # Returns an array with the "n" biggest clusters for A(already labeled)
    A =  np.copy(A_copy)
    unique = np.unique([~np.isnan(A)]) # unique labels which are numbers
    S = np.zeros(len(unique))          
    for i in range(len(unique)):
        S[i] = len(find_index(A, unique[i]))
    order = np.argsort(S)
    S, unique = S[order], unique[order]
    final_index = unique[~n:]          # extract the biggest "h" ones 
    for u in unique:
        if not np.isin(u, final_index):
            replace(A, u, 0)           # relabel with 0
    for i in range(n):
        replace(A, final_index[i], i+1) # relabel with 1,..,n
    return A
    
```

## cell 40 [markdown]
**Denoising**

## cell 41 [code]
```python
def denoise(A,B):
        # Cleans A with data from B
    C = np.zeros_like(A)                             # Final clean image
    for i in range(A.shape[0]):                      # loop over cells
        for j in range(A.shape[1]):
            if np.isnan(A[i,j]) or np.isnan(B[i,j]): # If there is NaN -> NaN
                C[i,j] = np.nan
            else:                                    # Id data ->  mean
                C[i,j] = np.arctan2(np.sin(A[i,j]) + np.sin(B[i,j]), np.cos(A[i,j]) + np.cos(B[i,j]))
    replace(C,0,np.nan)
    # return denoised image
    return C            
```

## cell 42 [markdown]
**Big Work** function

## cell 43 [code]
```python
def big_work2(N_Clusters,folder, n, lk_res, lk_win, lk_levels, rmin, thetamin, vmin, vmax):
    
    # Note we need at least 3 images in the folder.
    a1, v1, vectors1 = find_flow(folder, n, lk_res, lk_win, lk_levels)
    A1, V1 = get_angle(v1, lk_res, vmin, vmax)
    a2, v2, vectors2 = find_flow(folder, n+1, lk_res, lk_win, lk_levels)
    A2, V2 = get_angle(v2, lk_res, vmin, vmax)
    Angle = denoise(A1, A2)
    FRHK = float_range_hk(Angle, rmin, thetamin)
    #bc = FRHK #big_clusters(FRHK, N_Clusters)  # N_clusters biggest clusters
    bc = big_clusters(FRHK, N_Clusters)  # N_clusters biggest clusters
    bc = bc.astype(float)
    replace(bc,0,np.nan)
    return a1, bc, Angle, V1
```

## cell 44 [code]
```python
a1, bc, Angle, V1 = big_work2(20, "./pictures_Saturns/", 0, 50, 15, 4, 0, 0.1, 1, 20000)
```

## cell 45 [code]
```python
bc

```

## cell 46 [code]
```python
Angle
```

## cell 47 [code]
```python
V1
```

## cell 48 [code]
```python

```
