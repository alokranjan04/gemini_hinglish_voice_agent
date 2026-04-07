import json
import os

# The raw parts as provided
CREDENTIALS = {
    "type": "service_account",
    "project_id": "pdfdrive-461614",
    "private_key_id": "unknown",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCl4m+3mc+jCEZz\n83o387NKfFcvKJpSZ+fsJ5FEyCyeG0Rne51vXkhuir8j10Vl71NvUR/7J5jdA71X\na4uyzib2RpuaTNwbcJnr6BY+Z2l76yDsANvmIl15XdXN2ymFQdd6mboii7SydfHy\nPXK8SWEjDSok11MBxHzXOU4c8S0bYrNd9Lgv2zg7hCFZwHUna2ZuLNOt7hLYx5C0\neXOgov/jXiSsTJDCGt97Xow+6C+iJUvv3PXQPYFQ0RHciRTiLDDeoxcDM/eM1xEk\nXxc4YNmjNK54ooxxzV3qKRPOdHTQ7N3Y1hduWqklS54zl0FIPVsopAzTf8rXb/8H\nc1kmuimnAgMBAAECggEAD+P/G7FqSI3UYesi/BUmSa5bk7LqBZbaiq7HpbUfQQ4P\noXIgBLkdaylzYfWPOlKQxYsZ6y9B33oqOyOcQEarSNA+u6s9Mou40vZqmxPA8RP3\nFWSHrCYCmku43X1vHsrN33q2b/S+HJJb2P617P+ChJ8QOHNACl1OMDfXGcKotYS5\ndgJaz/XGHzqafBLqItU3Pgbt/6SXdSa6dqH6KymUNVH+G29ZW6PE2ax05PycHUgZ\nLlSuzQEp8e3LYIYnIJZZtk2/gN+Mg0f91xjqQnqVAlwGeliFrO25tjCk1b/vZiGA\n8DhGQ3xj3wJnKgqH7V7U6wZTVCTKBxholTzy7y8csQKBgQDUcX2V4xSAP6YdwpYF\n/T8p2FbQ76XE3w4AS7LczNF50O6wPdo5Yw9sclKjGH7lZSv35PuFNbZtzghCkMfD\nS0aceXvW1ke+2laTU8cZ5sY1IU6LPp/KHHMFBEPMdG05A/xLicPSWJz20JON6GW3\nS1LG4JCAh8lxhneNnPjnM6qylQKBgQDH5Tbqv5TNzLL3AOKTd4NVfYaTUPmkG4/8\nqIiTMUpU8IAdhH0S/PhYeKQ7TFq6djd0PTSUVUlyzb5mKLSxJCu0Vn7ZJYo3xC2/\n1GVezSABXBjUl8IA/WFA18Ws3wMwybjoXDvXz72PSXQKPZYY4C2a+ZHxfGVGzt+A\nG41wEXp4SwKBgHDYiBkiMjWdmaOdRQuRZgfYPuVlJuzYfxtxGmVm9q56aQ99C3oI\nQJ0ebP7teBpqD1zyaRht7CFPm9ugBDycs7lSXpHT6PBcEjjX+56qkwaN1qbocQBu\n9Dnp9gmYnpv2ngGSAE6ve1EvofFzTPR8MlAp4RglCMAg6Uhz5VMKgtWxAoGAZ3v6\nmjzkREacv9LteXp9u1xotwtMsfCy8hIt4kW6PY7kRGO6fIIJ74NFQo2cyrs4qiyl\nc8VTaOOqliisoqgfGBVPRgtxKr2dEZpbgGChGRMcp7KI9Qo3tuH9rCkn9bH40BIv\nyOH7OJrGQCbx9Z7Y/UoGjAXiSG4AtsmMx1/FD1ECgYBXI7k7/GdeAK21VXAQrVdZ\nEucmctAciUK/N0gMjzLbflBWhRkKNUG3lcwkZs1Etl5rw0mGkoKKoZpe7oj3gbf8\nDiNg4JgozWPa/Xl3Ev1RD3l0N6RufrcL1Zw28gEkBTYXhvHTZVpPPNP6z+q01lsc\nSeMhz2/nqoj3Rj8PdVby/w==\n-----END PRIVATE KEY-----\n",
    "client_email": "voice-ai-calendar@pdfdrive-461614.iam.gserviceaccount.com",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/voice-ai-calendar%40pdfdrive-461614.iam.gserviceaccount.com"
}

def fix_it():
    # Clean up the private key
    key = CREDENTIALS["private_key"]
    # Ensure standard newlines and no double-escaping
    key = key.replace("\\n", "\n")
    CREDENTIALS["private_key"] = key

    with open('google-credentials.json', 'w') as f:
        json.dump(CREDENTIALS, f, indent=2)
    print("google-credentials.json has been reconstructed successfully.")

if __name__ == "__main__":
    fix_it()
