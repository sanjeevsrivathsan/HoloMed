import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    SecondaryCaptureImageStorage,
    generate_uid,
)

filename = "test.dcm"

study_uid = generate_uid()
series_uid = generate_uid()
sop_uid = generate_uid()

meta = FileMetaDataset()
meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
meta.MediaStorageSOPInstanceUID = sop_uid
meta.TransferSyntaxUID = ExplicitVRLittleEndian
meta.ImplementationClassUID = generate_uid()

ds = FileDataset(
    filename,
    {},
    file_meta=meta,
    preamble=b"\0" * 128,
)

ds.PatientName = "Test^Patient"
ds.PatientID = "HOLOMED-TEST-001"

ds.StudyInstanceUID = study_uid
ds.SeriesInstanceUID = series_uid
ds.SOPInstanceUID = sop_uid

ds.Modality = "OT"

ds.Rows = 2
ds.Columns = 2
ds.SamplesPerPixel = 1
ds.PhotometricInterpretation = "MONOCHROME2"
ds.BitsAllocated = 8
ds.BitsStored = 8
ds.HighBit = 7
ds.PixelRepresentation = 0

ds.PixelData = np.array(
    [[0, 255], [255, 0]],
    dtype=np.uint8,
).tobytes()

ds.save_as(filename)

print(f"Created: {filename}")
print(f"StudyInstanceUID: {study_uid}")
print(f"SeriesInstanceUID: {series_uid}")
print(f"SOPInstanceUID: {sop_uid}")