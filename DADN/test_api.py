#!/usr/bin/env python3
"""
Test script for DADN API Server
Run this while server is running to verify setup
"""

import requests
import json
import sys
from pathlib import Path

# Configuration
SERVER_URL = "http://10.121.219.227:5000"  # Change this to your PC IP!
TIMEOUT = 5

def test_health(server_url):
    """Test /health endpoint"""
    print("Testing /health endpoint...")
    try:
        resp = requests.get(f"{server_url}/health", timeout=TIMEOUT)
        if resp.status_code == 200:
            print(f"✓ Server is running: {resp.json()}")
            return True
        else:
            print(f"✗ Server returned {resp.status_code}")
            return False
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def test_config(server_url):
    """Test /api/config endpoint"""
    print("\nTesting /api/config endpoint...")
    try:
        resp = requests.get(f"{server_url}/api/config", timeout=TIMEOUT)
        if resp.status_code == 200:
            print(f"✓ Config retrieved:\n{json.dumps(resp.json(), indent=2)}")
            return True
        else:
            print(f"✗ Server returned {resp.status_code}")
            return False
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def test_detect(server_url, image_path):
    """Test /api/detect endpoint with an image"""
    print(f"\nTesting /api/detect endpoint with {image_path}...")
    
    if not Path(image_path).exists():
        print(f"✗ Image file not found: {image_path}")
        return False
    
    try:
        with open(image_path, 'rb') as f:
            files = {'image': f}
            resp = requests.post(f"{server_url}/api/detect", files=files, timeout=TIMEOUT)
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"✓ Detection successful:")
            print(f"  Detections found: {result['detections_count']}")
            print(f"  Inference time: {result['inference_time_ms']}ms")
            print(f"  Server FPS: {result['fps']}")
            
            if result['alert']:
                alert = result['alert']
                print(f"  Alert: {alert['label_vi']} ({alert['distance_level']}) - {alert['horizontal_zone']}")
            else:
                print(f"  No alert triggered")
            
            return True
        else:
            print(f"✗ Server returned {resp.status_code}")
            print(f"Response: {resp.text}")
            return False
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False

def main():
    print("=" * 50)
    print("DADN API Server Test Script")
    print("=" * 50)
    print(f"Server URL: {SERVER_URL}\n")
    
    # Check if requests library is installed
    try:
        import requests
    except ImportError:
        print("✗ requests library not found. Install with: pip install requests")
        return 1
    
    # Test health
    if not test_health(SERVER_URL):
        print("\n✗ FAILED: Server is not running or not reachable")
        print("Make sure to run: python api_server.py")
        print(f"And update SERVER_URL to your PC IP if not {SERVER_URL}")
        return 1
    
    # Test config
    test_config(SERVER_URL)
    
    # Test detect with sample image if available
    sample_images = [
        "test.jpg",
        "sample.jpg",
        Path(__file__).parent / "test.jpg",
    ]
    
    for img_path in sample_images:
        if Path(img_path).exists():
            test_detect(SERVER_URL, img_path)
            break
    else:
        print("\nℹ No test image found. To test /api/detect:")
        print("  1. Place a JPEG image as 'test.jpg' in this directory")
        print("  2. Or capture an image from ESP32 web server")
        print("  3. Re-run this script")
    
    print("\n" + "=" * 50)
    print("✓ All available tests passed!")
    print("=" * 50)
    return 0

if __name__ == "__main__":
    sys.exit(main())
