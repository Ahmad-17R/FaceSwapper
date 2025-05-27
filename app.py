import uuid
import requests
import base64
import time
import logging
from io import BytesIO
from PIL import Image
from flask import Flask, request, send_file, jsonify
import os
# Config
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants / API Keys
IMGBB_API_KEY = "1728fd23e8dd52a4e2296153ab4504db"
FACE_SWAP_API_KEY = "aec81f77e11c4b09743a025d585942a075bc08f1cb4c8ab968eb878c337138c8"
AILAB_API_KEY = "0gFRV1T2fNMHzbBe4OnwmsOVphqQqIGf6XrwJZIsL5uE0y6Feo8Rcik3lQXydMi1"
AILAB_API_URL = "https://www.ailabapi.com/api/image/effects/ai-anime-generator"
AILAB_QUERY_URL = "https://www.ailabapi.com/api/image/asyn-task-results"

CARTOON_STYLE = 1  # 2D look
TASK_TYPE = "GENERATE_CARTOONIZED_IMAGE"
MAX_RESOLUTION = (2000, 2000)

# Utility Functions

def validate_image(image_data, filename):
    valid_formats = {'jpg', 'jpeg', 'png', 'bmp', 'webp'}
    ext = filename.rsplit('.', 1)[-1].lower()
    max_size_mb = 10
    if ext not in valid_formats:
        raise ValueError(f"Unsupported format. Must be one of {valid_formats}")
    if len(image_data) > max_size_mb * 1024 * 1024:
        raise ValueError(f"Image size must be <= {max_size_mb} MB")
    return True

def resize_image(image_data):
    logger.info("Checking if image needs resizing...")
    img = Image.open(BytesIO(image_data))
    if img.size[0] > MAX_RESOLUTION[0] or img.size[1] > MAX_RESOLUTION[1]:
        img.thumbnail(MAX_RESOLUTION)
        output = BytesIO()
        img.save(output, format="PNG")
        logger.info("Image resized")
        return output.getvalue()
    return image_data

def upload_to_imgbb(api_key, image_data):
    logger.info("Uploading image to imgbb...")
    encoded_image = base64.b64encode(image_data).decode()
    payload = {"key": api_key, "image": encoded_image}
    response = requests.post("https://api.imgbb.com/1/upload", data=payload)
    if response.ok:
        url = response.json()["data"]["url"]
        logger.info(f"Image uploaded: {url}")
        return url
    logger.error(f"imgbb upload failed: {response.text}")
    raise Exception(response.text)

# Face Swap Logic

def call_face_swap_api(api_key, target_url, swap_url):
    logger.info("Calling face swap API...")
    url = "https://api.piapi.ai/api/v1/task"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "model": "Qubico/image-toolkit",
        "task_type": "face-swap",
        "input": {"target_image": target_url, "swap_image": swap_url}
    }
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    if response.ok and data.get("code") == 200:
        task_id = data["data"]["task_id"]
        logger.info(f"Face swap task started. ID: {task_id}")
        return task_id
    logger.error(f"Face swap API failed: {data}")
    raise Exception(data)

def poll_face_swap_task(api_key, task_id, max_attempts=40, wait_seconds=3):
    logger.info(f"Polling task {task_id}...")
    url = f"https://api.piapi.ai/api/v1/task/{task_id}"
    headers = {"x-api-key": api_key}
    for attempt in range(max_attempts):
        response = requests.get(url, headers=headers)
        if not response.ok:
            raise Exception(f"Poll failed: {response.text}")
        data = response.json()
        status = data["data"].get("status")
        logger.info(f"[Attempt {attempt + 1}] Status: {status}")
        if status == "completed":
            image_url = data["data"]["output"].get("image_url")
            if image_url:
                result = requests.get(image_url)
                if result.ok:
                    return result.content
                else:
                    raise Exception("Image download failed")
        elif status.lower() in ["failed", "timeout_failed"]:
            raise Exception(f"Task failed with status: {status}")
        time.sleep(wait_seconds)
    raise Exception("Polling timed out.")

# Cartoonify Logic

def cartoonify_image(image_data, style_index, filename):
    logger.info("Starting cartoonify process...")
    image_data = resize_image(image_data)
    validate_image(image_data, filename)
    headers = {"ailabapi-api-key": AILAB_API_KEY}
    files = {"image": (filename, image_data)}
    data = {"task_type": "async", "index": style_index}
    
    response = requests.post(AILAB_API_URL, headers=headers, files=files, data=data)
    response_data = response.json()

    if not response.ok or response_data.get("error_code") != 0:
        raise Exception(f"AILab API Error: {response_data.get('error_msg')}")

    request_id = response_data["request_id"]
    logger.info(f"Cartoonify request submitted. ID: {request_id}")

    for attempt in range(360):
        params = {"job_id": request_id, "type": TASK_TYPE}
        query = requests.get(AILAB_QUERY_URL, headers=headers, params=params)
        query_data = query.json()
        status = query_data.get("data", {}).get("status")
        logger.info(f"[Attempt {attempt + 1}] Cartoonify status: {status}")
        
        if status == "PROCESS_SUCCESS":
            result_url = query_data["data"]["result_url"]
            final_img = requests.get(result_url)
            if final_img.ok:
                return final_img.content
            else:
                raise Exception("Final image download failed")
        elif status in ["PROCESS_FAILED", "TIMEOUT_FAILED", "LIMIT_RETRY_FAILED"]:
            raise Exception(f"Task failed: {status}")
        time.sleep(5)

    raise Exception("Cartoonify process timed out.")

# API Endpoint

@app.route("/swap-and-cartoonify", methods=["POST"])
def swap_and_cartoonify_endpoint():
    logger.info("Incoming request: /swap-and-cartoonify")
    if "target_image" not in request.files or "swap_image" not in request.files:
        return jsonify({"error": "Missing target_image or swap_image"}), 400

    target_img = request.files["target_image"]
    swap_img = request.files["swap_image"]

    target_data = target_img.read()
    swap_data = swap_img.read()

    target_filename = f"{uuid.uuid4().hex}_{target_img.filename}"
    swap_filename = f"{uuid.uuid4().hex}_{swap_img.filename}"

    try:
        target_url = upload_to_imgbb(IMGBB_API_KEY, target_data)
        swap_url = upload_to_imgbb(IMGBB_API_KEY, swap_data)

        task_id = call_face_swap_api(FACE_SWAP_API_KEY, target_url, swap_url)
        swapped_image = poll_face_swap_task(FACE_SWAP_API_KEY, task_id)

        cartoonified_image = cartoonify_image(swapped_image, CARTOON_STYLE, "swapped.png")

        return send_file(BytesIO(cartoonified_image), mimetype="image/png", as_attachment=True, download_name="cartoonified.png")

    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Run App
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
