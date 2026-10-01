# AHN4 Vegetation Classification Labels

Per-point vegetation labels for the Dutch national point cloud **AHN4**, published as small
label files (`*.cls`) instead of full copies of the point clouds.

In the original AHN4 tiles, vegetation points are left as class `1` (unclassified).
This dataset assigns class **`5` (vegetation)** to them. The label files hold only the
class id of each point. You download the original AHN4 tiles yourself and
`ahn4_classification_decode_v_1.0.py` attaches the labels to them.

| | Size (tile `C_27CZ2`, 1,182,035,054 points) |
|---|---|
| Original AHN4 tile (`.LAZ`) | 9.1 GB |
| Full classified copy (`.laz`) | 9.1 GB |
| **Label file (`.cls`)** | **118.5 MB** |

See [Data volume](#data-volume-national-estimate) for the estimate for the whole country.

---

## Contents

```
ahn4_classification_decode_v_1.0.py   decoder (the only script you need)
labels/                               one <TILE>.cls per AHN4 tile
README.md
```

---

## Requirements

- Python ≥ 3.8
- `numpy`, `laspy` ≥ 2.0 with LAZ support:

```bash
pip install numpy "laspy[lazrs]"
```

Memory use is about 1 GB, whatever the tile size. Decoding a 1.2-billion-point tile takes
about 1.5 minutes on a desktop machine (32 cores, NVMe disk).

---

## Quick start

### 1. Get the original AHN4 tiles

Download the original AHN4 LAZ tiles you need from:

> **TODO: exact download source and AHN4 version/date of the tiles the labels were made against**

Each `.cls` file only works with the **exact original tile** it was made from (same points,
same point order). The decoder checks this automatically (see [Safety checks](#safety-checks)).

### 2. Arrange the folders

```
my_folder/
├── ahn4_classification_decode_v_1.0.py
├── C_27CZ2.cls                  ← label files
├── C_xxxxx.cls
└── original/
    ├── C_27CZ2.LAZ              ← original AHN4 tiles (file name = tile name, any case)
    └── C_xxxxx.LAZ
```

### 3. Run

```bash
python3 ahn4_classification_decode_v_1.0.py
```

You can also press **Run** in VS Code or another IDE. Every `*.cls` file is matched to
`original/<TILE>.LAZ` and written to:

```
my_folder/decoded/<TILE>_classified.laz
```

Tiles that already have an output are skipped. To use different folders, edit the
`CONFIG` block at the top of the script:

```python
ORIGINAL_DIR = "original"   # folder with the original AHN4 tiles
LABEL_DIR = "."             # folder with the *.cls label files
OUTPUT_DIR = "decoded"      # classified tiles are written here
OUTPUT_EXT = ".laz"         # ".laz" (compressed) or ".las"
OVERWRITE = False           # False: skip tiles whose output already exists
```

The output is a copy of the original tile with **only the classification replaced**. It keeps
the same LAS version (1.4), point format, point order, coordinates, GPS time and the AHN4
extra bytes (`Reflectance`, `Deviation`).

---

## Command line

```bash
# one tile -> classified LAZ (or .las)
python3 ahn4_classification_decode_v_1.0.py apply   original/C_27CZ2.LAZ C_27CZ2.cls C_27CZ2_classified.laz

# one tile -> labels only, as a NumPy array (.npy), in original point order
python3 ahn4_classification_decode_v_1.0.py extract original/C_27CZ2.LAZ C_27CZ2.cls C_27CZ2_labels.npy

# every *.cls in a folder
python3 ahn4_classification_decode_v_1.0.py batch   original/ labels/ decoded/ [--las] [--overwrite]

# summary of a label file (point count, fingerprint, class histogram)
python3 ahn4_classification_decode_v_1.0.py info    C_27CZ2.cls
```

Example `info` output:

```
file   : C_27CZ2.cls
points : 1,182,035,054
codec  : lzma
sha256 : b663511f53f20ec935b4f3e6d93019840a4b52950b9ac60ef1815fc6921b3fa5
class   1:     18,749,192  (  1.59%)
class   2:    560,561,443  ( 47.42%)
class   5:    602,593,329  ( 50.98%)
class   6:        128,813  (  0.01%)
class   9:          2,277  (  0.00%)
```

---

## Use from Python

You can use the labels without writing a new LAZ file:

```python
import importlib.util
import laspy

spec = importlib.util.spec_from_file_location("ahn4dec", "ahn4_classification_decode_v_1.0.py")
ahn4dec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ahn4dec)

labels = ahn4dec.load_labels("original/C_27CZ2.LAZ", "C_27CZ2.cls")   # numpy uint8, one per point

las = laspy.read("original/C_27CZ2.LAZ")      # note: a full tile needs a lot of RAM
las.classification = labels
vegetation = las.points[labels == 5]
```

`load_labels` raises `FingerprintError` if the label file does not belong to the tile.

---

## Class codes

| Code | Meaning | Source |
|---|---|---|
| 1 | Unclassified (remaining points) | AHN4 |
| 2 | Ground | AHN4 |
| **5** | **Vegetation, all heights** | **this dataset** |
| 6 | Building | AHN4 |
| 9 | Water | AHN4 |

Only points of AHN4 class `1` were reclassified. All other AHN4 classes are passed
through unchanged. In tile `C_27CZ2`, 602,593,329 of the 621,342,521 class-1 points became class `5`.

> In the ASPRS LAS standard, code 5 means *high* vegetation (3 = low, 4 = medium).
> In this dataset, **5 means all vegetation**, regardless of height.

---

## Safety checks

Each `.cls` file stores a fingerprint (SHA-256) of the X/Y/Z coordinates of the original tile,
in point order. The decoder recomputes it while reading the tile. If any of the following
happens, it stops and **writes nothing**:

| Situation | Message |
|---|---|
| Different tile, AHN version, or re-ordered/re-processed copy | `FINGERPRINT MISMATCH: ... does not belong to ...` |
| Different number of points | `FINGERPRINT MISMATCH: label file is for N points, ... has M` |
| Truncated or corrupt `.cls` download | `ERROR: label stream ended early (corrupt or truncated .cls file)` |
| No original tile for a `.cls` (batch mode) | `SKIPPED: no <TILE>.LAZ in ...` |

If you get a fingerprint mismatch, you most likely downloaded a different version of the
original tile than the one the labels were made against (see [step 1](#1-get-the-original-ahn4-tiles)).

---

## Data volume (national estimate)

This is an estimate, scaled up from one tile (`C_27CZ2`). It is not a measured total.

| | Tile `C_27CZ2` (measured) | All of AHN4 (estimated) |
|---|---|---|
| Points | 1,182,035,054 | ≈ 833 billion |
| Original LAZ | 9.09 GB (7.69 bytes/point) | 6,408.6 GB ¹ |
| Full classified copies | 9.10 GB | ≈ 6.4 TB |
| Labels, uncompressed (1 byte/point) | 1.18 GB | ≈ 833 GB |
| **Label files (`.cls`)** | **118.5 MB (0.80 bits/point, 1.3 % of the LAZ)** | **≈ 50–85 GB** |

How the estimate is derived:

- The national point count is the total AHN4 LAZ volume ¹ divided by this tile's 7.69 bytes/point.
  As a check, that count over the area of the Netherlands (≈ 41,500 km² including water) gives
  ≈ 20 points/m², consistent with the published AHN4 density of 20–30 points/m² ¹.
- The upper bound (≈ 84 GB) assumes this tile's 0.80 bits/point holds everywhere. This tile is
  probably a heavy case: 37.8 points/m² and 51 % vegetation. Labels in urban, agricultural and
  water tiles are more uniform and compress better, which is why the range extends down to ≈ 50 GB.
  The lower bound is a rough assumption (≈ 0.5 bits/point). It is not measured.
- The national LAZ volume comes from a single source. Its file counts are not internally
  consistent, so treat the total as approximate.

¹ Shi, Y., Wang, J., and Kissling, W. D. (2025). Multi-temporal high-resolution data products of
ecosystem structure derived from country-wide airborne laser scanning surveys of the Netherlands.
*Earth System Science Data*, 17, 3641–3677. <https://doi.org/10.5194/essd-17-3641-2025>

> **TODO:** replace this estimate with the measured total once all tiles are encoded
> (`python3 ahn4_classification_decode_v_1.0.py info <TILE>.cls` reports each tile's point count; the `.cls` file sizes give the total).

---

## Label file format (`AHNCLS01`)

All values little-endian.

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic `b"AHNCLS01"` |
| 8 | 8 | `uint64` number of points |
| 16 | 1 | `uint8` codec: `1` = zlib stream, `2` = xz/LZMA stream |
| 17 | 7 | reserved (zeros) |
| 24 | 32 | SHA-256 fingerprint of the original tile: for each consecutive block of 10,000,000 points (last block shorter), in point order, the raw `int32` X values, then Y, then Z |
| 56 | … | compressed stream of *number of points* `uint8` class ids, in the point order of the original tile |

The format is simple enough to read without the script. Decompress the stream after byte 56
and you have one byte per point.

---

## License

> **TODO:** license of the label files and the script.
> AHN4 itself is open data published by the Dutch government. Check its license terms before redistributing derived data.

## Citation

> **TODO:** how to cite this dataset.

## Contact

> **TODO**
