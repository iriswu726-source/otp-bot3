import cv2
import base64
import struct
from urllib.parse import unquote
import glob

def decode_qr(filename):
    img = cv2.imread(filename)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    return data

def parse_migration(data):
    from google.protobuf import descriptor_pb2
    payload = data.split("data=")[1]
    payload = unquote(payload)
    # 補齊 base64 padding
    payload += "=" * (4 - len(payload) % 4)
    decoded = base64.b64decode(payload)
    
    # 手動解析 protobuf
    accounts = []
    i = 0
    while i < len(decoded):
        if decoded[i] == 0x0a:  # field 1, type 2 (length-delimited)
            i += 1
            length = decoded[i]
            i += 1
            entry = decoded[i:i+length]
            i += length
            
            # 解析每個帳號
            j = 0
            secret = None
            name = None
            issuer = None
            while j < len(entry):
                field_type = entry[j]
                j += 1
                if field_type == 0x0a:  # secret
                    l = entry[j]; j += 1
                    secret = base64.b32encode(entry[j:j+l]).decode().rstrip('=')
                    j += l
                elif field_type == 0x12:  # name
                    l = entry[j]; j += 1
                    name = entry[j:j+l].decode('utf-8', errors='ignore')
                    j += l
                elif field_type == 0x1a:  # issuer
                    l = entry[j]; j += 1
                    issuer = entry[j:j+l].decode('utf-8', errors='ignore')
                    j += l
                else:
                    break
            
            if secret:
                accounts.append({"name": name or issuer or "Unknown", "secret": secret})
        else:
            i += 1
    
    return accounts

# 讀取所有 qr*.png
all_accounts = []
for qr_file in sorted(glob.glob("qr*.png")):
    print(f"讀取 {qr_file}...")
    data = decode_qr(qr_file)
    if data and "otpauth-migration" in data:
        accounts = parse_migration(data)
        all_accounts.extend(accounts)
    else:
        print(f"  ❌ 無法讀取或不是正確格式")

print("\n===== 所有帳號 =====")
print('ACCOUNTS = {')
for acc in all_accounts:
    print(f'    "{acc["name"]}": "{acc["secret"]}",')
print('}')