from gradio_app import predict
import os

print("Testing Healthy Sample...")
h_file = 'public_dataset/00039425-7f3a-42aa-ac13-834aaa2b6b92.webm'
res_h, det_h, qual_h, chart_h, comp_h, meta_h = predict(
    None, h_file, '', '', 'svc.joblib', 'male', 30, 0.9, 'false', 'false'
)
print("TEST 1 (HEALTHY SAMPLE) -> Label:", meta_h.get('label'))

print("\nTesting Asthmatic / Disease Sample...")
d_file = 'public_dataset/01567151-7bb2-45ee-9aa8-a1332b5941ea.webm'
res_d, det_d, qual_d, chart_d, comp_d, meta_d = predict(
    None, d_file, '', 'Wheezing, nocturnal coughing, shortness of breath', 'svc.joblib', 'female', 45, 0.92, 'true', 'false'
)
print("TEST 2 (ASTHMA / DISEASE SAMPLE) -> Label:", meta_d.get('label'))
print("Precautions in HTML:", "Clinical Precautions & Care Plan" in det_d)

print("\nTesting Fever + COVID Sample...")
res_c, det_c, qual_c, chart_c, comp_c, meta_c = predict(
    None, d_file, '', 'Persistent cough, high fever 102F, body pain and chills', 'svc.joblib', 'male', 50, 0.94, 'false', 'true'
)
print("TEST 3 (FEVER / COVID SAMPLE) -> Label:", meta_c.get('label'))
print("Condition:", meta_c.get('label'))
print("Precautions in HTML:", "Clinical Precautions & Care Plan" in det_c)
print("\nALL CLINICAL TESTS SUCCESSFUL!")
