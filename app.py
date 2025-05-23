import os
import uuid
import requests
import base64
import time
import logging
from PIL import Image
from flask import Flask, request, send_file, jsonify

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# API keys and constants
IMGBB_API_KEY = "1728fd23e8dd52a4e2296153ab4504db"
FACE_SWAP_API_KEY = "aec81f77e11c4b09743a025d585942a075bc08f1cb4c8ab968eb878c337138c8"
CARTOON_API_KEY = "cd0026142fmsh6acf1b6045d0a92p1b7597jsn062e4a854da6"
CARTOON_API_HOST = "cartoon-yourself.p.rapidapi.com"
CARTOON_API_URL = "https://cartoon-yourself.p.rapidapi.com/facebody/api/portrait-animation/portrait-animation"

CARTOON_STYLE = "hongkong"
UPLOAD_FOLDER = "/tmp/uploads"  # Use /tmp for Render compatibility
RESULT_FOLDER = "/tmp/results"
MAX_RESOLUTION = (2000, 2000)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULT_FOLDER, exist_ok=True)

def upload_to_imgbb(api_key, image_path):
    logger.info(f"Uploading image to imgbb: {image_path}")
    with open(image_path, "rb") as f:
        encoded_image = base64.b64encode(f.read()).decode()

    payload = {
        "key": api_key,
        "image": encoded_image
    }

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
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "Qubico/image-toolkit",
        "task_type": "face-swap",
        "input": {
            "target_image": target_image_url,
            "swap_image": swap_image_url
        }
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
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }

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
            logger.info(f"Output content: {output}")
            if output and "image_url" in output:
                image_url = output["image_url"]
                img_response = requests.get(image_url)
                if img_response.status_code == 200:
                    swapped_path = os.path.join(RESULT_FOLDER, f"swapped_{uuid.uuid4().hex}.jpg")
                    with open(swapped_path, "wb") as f:
                        f.write(img_response.content)
                    logger.info(f"Swapped image saved to: {swapped_path}")
                    return swapped_path
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

def resize_image(image_path):
    logger.info(f"Resizing image if necessary: {image_path}")
    img = Image.open(image_path)
    if img.width > MAX_RESOLUTION[0] or img.height > MAX_RESOLUTION[1]:
        img.thumbnail(MAX_RESOLUTION)
        resized_path = os.path.join(UPLOAD_FOLDER, f"resized_{os.path.basename(image_path)}")
        img.save(resized_path)
        logger.info(f"Image resized and saved to: {resized_path}")
        return resized_path
    logger.info("No resizing needed")
    return image_path

def cartoonify_image(image_path, style):
    logger.info(f"Cartoonifying image: {image_path}")
    image_path = resize_image(image_path)

    with open(image_path, "rb") as img_file:
        files = {"image": img_file}
        data = {"type": style}
        headers = {
            "x-rapidapi-key": CARTOON_API_KEY,
            "x-rapidapi-host": CARTOON_API_HOST,
        }

        response = requests.post(CARTOON_API_URL, headers=headers, files=files, data=data)

        if response.status_code == 200:
            resp_json = response.json()
            image_url = resp_json.get("data", {}).get("image_url")
            if image_url:
                logger.info(f"Downloading cartoonified image from: {image_url}")
                download_response = requests.get(image_url)
                if download_response.status_code == 200:
                    output_path = os.path.join(RESULT_FOLDER, f"cartoon_{uuid.uuid4().hex}.png")
                    with open(output_path, "wb") as f:
                        f.write(download_response.content)
                    logger.info(f"Cartoonified image saved to: {output_path}")
                    return output_path
                else:
                    logger.error("Failed toa to download cartoon image")
                    raise Exception("Failed to download cartoon image.")
            else:
                logger.error("No image URL found in cartoon API response")
                raise Exception("No image URL found in cartoon API response.")
        else:
            logger.error(f"Cartoonify API error: {response.status_code}, {response.text}")
            raise Exception(f"Cartoonify API error: {response.status_code}, {response.text}")

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

    target_path = os.path.join(UPLOAD_FOLDER, target_filename)
    swap_path = os.path.join(UPLOAD_FOLDER, swap_filename)

    logger.info(f"Saving target image to: {target_path}")
    target_image.save(target_path)
    logger.info(f"Saving swap image to: {swap_path}")
    swap_image.save(swap_path)

    try:
        # Step 1: Upload images to imgbb
        target_url = upload_to_imgbb(IMGBB_API_KEY, target_path)
        swap_url = upload_to_imgbb(IMGBB_API_KEY, swap_path)

        # Step 2: Perform face swap
        task_id = call_face_swap_api(FACE_SWAP_API_KEY, target_url, swap_url)
        swapped_image_path = poll_face_swap_task(FACE_SWAP_API_KEY, task_id)

        # Step 3: Cartoonify the swapped image
        cartoon_image_path = cartoonify_image(swapped_image_path, CARTOON_STYLE)

        # Step 4: Calculate and print total time taken
        end_time = time.time()
        total_time = end_time - start_time
        logger.info(f"Total time taken for the entire process: {total_time:.2f} seconds")

        return send_file(cartoon_image_path, mimetype="image/png")

    except Exception as e:
        logger.error(f"Error in processing: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up temporary files
        for path in [target_path, swap_path]:
            if os.path.exists(path):
                logger.info(f"Cleaning up: {path}")
                os.remove(path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)