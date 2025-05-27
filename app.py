import uuid
import requests
import base64
import time
import logging
from io import BytesIO
from PIL import Image
from flask import Flask, request, send_file, jsonify

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# API keys and constants
IMGBB_API_KEY = "1728fd23e8dd52a4e2296153ab4504db"
FACE_SWAP_API_KEY = "aec81f77e11c4b09743a025d585942a075bc08f1cb4c8ab968eb878c337138c8"
AILAB_API_KEY = "Xo2ALYhoKs01siSpQf2RmY7PDO4eaDvv5MkFlyWCTfnczGTSNIHrAV8wEJMjxqqe"
AILAB_API_URL = "https://www.ailabapi.com/api/image/effects/ai-anime-generator"
AILAB_QUERY_URL = "https://www.ailabapi.com/api/image/asyn-task-results"
CARTOON_STYLE = 1  # Two-dimensional (2D) style
TASK_TYPE = "GENERATE_CARTOONIZED_IMAGE"
MAX_RESOLUTION = (2000, 2000)

def upload_to_imgbb(api_key, image_data):
    logger.info("Uploading image to imgbb")
    encoded_image = base64.b64encode(image_data).decode()
    payload = {"key": api_key, "image": encoded_image}
    response = requests.post("https://api.imgbb.com/1/upload", data=payload)
    if response.status_code == 200:
        url = response.json()["data"]["url"]
        logger.info(f"Image uploaded successfully: {url}")
        return url
    else:
        logger.error(f"Failed to upload image to imgbb: {response.text}")
        raise Exception(f"Failed to upload image to imgbb: {response.text}")

def call_face_swap_api(api_key, target_image_url, swap_image_url):
    logger.info("Calling face swap API")
    url = "https://api.piapi.ai/api/v1/task"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "model": "Qubico/image-toolkit",
        "task_type": "face-swap",
        "input": {"target_image": target_image_url, "swap_image": swap_image_url}
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        logger.info(f"API Response: {data}")
        if data.get("code") == 200 and "data" in data:
            task_id = data["data"]["task_id"]
            logger.info(f"Task submitted. Task ID: {task_id}")
            return task_id
        else:
            logger.error(f"Error in face swap response: {data}")
            raise Exception(f"Error in face swap response: {data}")
    else:
        logger.error(f"Face swap request failed: {response.status_code} - {response.text}")
        raise Exception(f"Face swap request failed: {response.status_code} - {response.text}")

def poll_face_swap_task(api_key, task_id, max_attempts=40, wait_seconds=3):
    logger.info(f"Polling for face swap task completion: {task_id}")
    url = f"https://api.piapi.ai/api/v1/task/{task_id}"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    for attempt in range(1, max_attempts + 1):
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to get task status: {response.status_code} - {response.text}")
            raise Exception(f"Failed to get task status: {response.status_code} - {response.text}")
        data = response.json()
        status = data["data"].get("status", "unknown")
        logger.info(f"Attempt {attempt}: Task status = {status}")
        if status == "completed":
            output = data["data"].get("output")
            if output and "image_url" in output:
                image_url = output["image_url"]
                img_response = requests.get(image_url)
                if img_response.status_code == 200:
                    logger.info("Swapped image retrieved successfully")
                    return img_response.content
                else:
                    logger.error(f"Failed to download image from result URL: {img_response.status_code}")
                    raise Exception(f"Failed to download image from result URL: {img_response.status_code}")
            else:
                logger.error("No image_url found in output")
                raise Exception("No image_url found in output.")
        elif status == "Failed":
            error = data["data"].get("error", {})
            logger.error(f"Task failed. Error: {error.get('message', 'No error message provided')}")
            raise Exception(f"Task failed. Error: {error.get('message', 'No error message provided')}")
        time.sleep(wait_seconds)
    logger.error("Task did not complete within the given attempts")
    raise Exception("Task did not complete within the given attempts.")

def resize_image(image_data):
    logger.info("Resizing image if necessary")
    img = Image.open(BytesIO(image_data))
    if img.width > MAX_RESOLUTION[0] or img.height > MAX_RESOLUTION[1]:
        img.thumbnail(MAX_RESOLUTION)
        output = BytesIO()
        img.save(output, format="PNG")
        logger.info("Image resized")
        return output.getvalue()
    logger.info("No resizing needed")
    return image_data

def validate_image(image_data, filename):
    valid_formats = {'jpg', 'jpeg', 'png', 'bmp', 'webp'}
    max_size_mb = 10
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext not in valid_formats:
        raise ValueError(f"Image format must be one of {valid_formats}")
    if len(image_data) > max_size_mb * 1024 * 1024:
        raise ValueError(f"Image size must not exceed {max_size_mb} MB")
    return True

def cartoonify_image(image_data, cartoon_style, filename):
    logger.info("Cartoonifying image")
    image_data = resize_image(image_data)
    try:
        validate_image(image_data, filename)
    except ValueError as e:
        logger.error(f"Image validation failed: {str(e)}")
        raise Exception(f"Image validation failed: {str(e)}")
    headers = {"ailabapi-api-key": AILAB_API_KEY}
    files = {'image': (filename, image_data)}
    data = {'task_type': 'async', 'index': cartoon_style}
    response = requests.post(AILAB_API_URL, headers=headers, files=files, data=data)
    if response.status_code != 200:
        logger.error(f"AILabTools API request failed: {response.status_code} - {response.text}")
        raise Exception(f"AILabTools API request failed: {response.status_code} - {response.text}")
    response_data = response.json()
    if response_data.get("error_code") != 0:
        logger.error(f"AILabTools API error: {response_data.get('error_msg')}")
        raise Exception(f"AILabTools API error: {response_data.get('error_msg')}")
    request_id = response_data.get("request_id")
    logger.info(f"Cartoonification task initiated with request ID: {request_id}")
    max_attempts = 360
    for attempt in range(max_attempts):
        params = {"job_id": request_id, "type": TASK_TYPE}
        query_response = requests.get(AILAB_QUERY_URL, headers=headers, params=params)
        if query_response.status_code != 200:
            logger.error(f"Failed to query task status: {query_response.status_code} - {query_response.text}")
            raise Exception(f"Failed to query task status: {query_response.status_code} - {query_response.text}")
        query_data = query_response.json()
        if query_data.get("error_code") != 0:
            logger.error(f"AILabTools query API error: {query_data.get('error_msg')}")
            raise Exception(f"AILabTools query API error: {query_data.get('error_msg')}")
        task_status = query_data.get("data", {}).get("status")
        result_url = query_data.get("data", {}).get("result_url")
        logger.info(f"Attempt {attempt + 1}: Task status = {task_status}")
        if task_status == "PROCESS_SUCCESS":
            if result_url:
                download_response = requests.get(result_url)
                if download_response.status_code == 200:
                    logger.info("Cartoonified image retrieved successfully")
                    return download_response.content
                else:
                    logger.error(f"Failed to download cartoon image: {download_response.status_code}")
                    raise Exception(f"Failed to download cartoon image: {download_response.status_code}")
            else:
                logger.error("No result URL found in response")
                raise Exception("No result URL found in response")
        elif task_status in ["PROCESS_FAILED", "TIMEOUT_FAILED", "LIMIT_RETRY_FAILED"]:
            logger.error(f"Cartoonification task failed with status: {task_status}")
            raise Exception(f"Cartoonification task failed with status: {task_status}")
        time.sleep(5)
    logger.error("Cartoonification task did not complete within 30 minutes")
    raise Exception("Cartoonification task did not complete within 30 minutes")

@app.route("/swap-and-cartoonify", methods=["POST"])
def swap_and_cartoonify_endpoint():
    logger.info("Received request at /swap-and-cartoonify endpoint")
    start_time = time.time()
    if "target_image" not in request.files or "swap_image" not in request.files:
        logger.error("Missing target_image or swap_image in request")
        return jsonify({"error": "Both target_image and swap_image files are required"}), 400
    target_image = request.files["target_image"]
    swap_image = request.files["swap_image"]
    target_filename = f"{uuid.uuid4().hex}_{target_image.filename}"
    swap_filename = f"{uuid.uuid4().hex}_{swap_image.filename}"
    target_data = target_image.read()
    swap_data = swap_image.read()
    try:
        # Step 1: Upload images to imgbb
        target_url = upload_to_imgbb(IMGBB_API_KEY, target_data)
        swap_url = upload_to_imgbb(IMGBB_API_KEY, swap_data)
        # Step 2: Perform face swap
        task_id = call_face_swap_api(FACE_SWAP_API_KEY, target_url, swap_url)
        swapped_image_data = poll_face_swap_task(FACE_SWAP_API_KEY, task_id)
        # Step 3: Cartoonify the swapped image
        cartoon_image_data = cartoonify_image(swapped_image_data, CARTOON_STYLE, "swapped_image.png")
        # Step 4: Calculate and log total time taken
        end_time = time.time()
        total_time = end_time - start_time
        logger.info(f"Total time taken for the entire process: {total_time:.2f} seconds")
        return send_file(BytesIO(cartoon_image_data), mimetype="image/png", download_name="cartoonified_image.png")
    except Exception as e:
        logger.error(f"Error in processing: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)