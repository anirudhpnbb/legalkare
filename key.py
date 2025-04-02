import os
import binascii

# Generate a 24-byte random key and convert it to a hex string
temporary_secret_key = binascii.hexlify(os.urandom(24)).decode()
print(temporary_secret_key)
