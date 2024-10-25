import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import mimetypes
import re
import argparse
import json
from tqdm import tqdm
import logging
import subprocess
import logging.handlers
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from datetime import datetime
from pathlib import Path

# Function to create a session with provided cookies
def create_session(cookies):
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])
    return session

# Function to sanitize filenames and directory names
def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

# Function to get the file name from the response headers
def get_filename_from_cd(cd):
    if not cd:
        return None
    fname = None
    if 'filename' in cd:
        fname = cd.split('filename=')[-1].strip().strip('"')
    return fname

# Function to download a file
def process_video(filepath, target_fps=1):
    """Process video to change its FPS using ffmpeg"""
    try:
        filepath = Path(filepath)
        print(f"\nProcessing video: {filepath}")
        output_path = filepath.with_suffix(filepath.suffix + '.tmp')
        
        # Convert paths to forward slashes and make them absolute
        input_path = str(filepath.absolute()).replace('\\', '/')
        output_path_str = str(output_path.absolute()).replace('\\', '/')
        
        # Use ffmpeg to change FPS
        cmd = [
            'ffmpeg', '-i', input_path,
            '-filter:v', f'fps={target_fps}',
            '-c:v', 'libx264',  # Use H.264 codec
            '-preset', 'fast',   # Fast encoding
            '-c:a', 'copy',      # Copy audio without re-encoding
            '-y',                # Overwrite output file if exists
            output_path_str
        ]
        
        print(f"Converting to {target_fps} FPS...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Wait for the process to complete
        stdout, stderr = process.communicate()
        
        if process.returncode == 0:
            filepath.unlink()
            output_path.rename(filepath)
            print("Video processing completed successfully")
        else:
            print(f"Error processing video: {stderr}")
            if output_path.exists():
                output_path.unlink()
            raise Exception(f"ffmpeg failed with return code {process.returncode}")
            
    except Exception as e:
        print(f"\nError processing video {filepath}: {str(e)}")
        logging.error(f"Error processing video {filepath}: {str(e)}")

def download_file(session, file_url, download_dir, max_size=None, overwrite=False, max_retries=3, process_videos=True):
    for attempt in range(max_retries):
        try:
            response = session.get(file_url, stream=True, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            })
            break
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logging.error(f"Failed to download {file_url} after {max_retries} attempts: {str(e)}")
                return False
            logging.warning(f"Attempt {attempt + 1} failed, retrying...")
            continue
    if response.status_code == 200:
        # Get filename from content-disposition
        filename = get_filename_from_cd(response.headers.get('content-disposition'))
        if not filename:
            # Fallback to the URL basename
            filename = os.path.basename(urllib.parse.urlparse(file_url).path)
            # If no extension, guess based on content type
            if '.' not in filename:
                ext = mimetypes.guess_extension(response.headers.get('content-type', '').split(';')[0].strip())
                if ext:
                    filename += ext
        
        filename = sanitize_filename(filename)
        download_path_with_extension = os.path.join(download_dir, filename)
        
        if not overwrite and os.path.exists(download_path_with_extension):
            logging.info(f"Skipping existing file: {filename}")
            return True
            
        # Check file size
        total_size = int(response.headers.get('content-length', 0))
        if max_size and total_size > max_size * 1024 * 1024:  # Convert MB to bytes
            logging.warning(f"Skipping {filename}: Size {total_size/(1024*1024):.1f}MB exceeds limit of {max_size}MB")
            return False
        
        # Get file size for progress bar
        total_size = int(response.headers.get('content-length', 0))
        
        # Use position parameter for tqdm to avoid interference with logging
        position = threading.current_thread().ident % 10
        with tqdm(total=total_size, unit='iB', unit_scale=True, desc=filename,
                 position=position, leave=False) as pbar:
            with open(download_path_with_extension, 'wb') as file:
                for chunk in response.iter_content(1024):
                    size = file.write(chunk)
                    pbar.update(size)
        
        # Process video if it's a video file and processing is enabled
        mime_type = mimetypes.guess_type(download_path_with_extension)[0]
        if process_videos and mime_type and mime_type.startswith('video'):
            print(f"\nDetected video file: {filename}")
            print(f"MIME type: {mime_type}")
            process_video(download_path_with_extension)
        
        return True
    else:
        print(f"Failed to download: {file_url} (Status code: {response.status_code})")
        return False

# Function to recursively download all files in a folder
def download_folder_files(session, folder_url, download_dir, max_size=None, overwrite=False, max_workers=3, process_videos=True):
    response = session.get(folder_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    })
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find all links to files and subfolders
    links = soup.find_all('a', href=True, class_="il_ContainerItemTitle")
    futures = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for link in links:
            href = link['href']
            href = urllib.parse.urljoin(folder_url, href)

            # Check if the link is a file or a folder
            if 'goto.php?target=file_' in href:
                logging.info(f"Found file: {href}")
                future = executor.submit(
                    download_file, 
                    session, 
                    href, 
                    download_dir,
                    max_size,
                    overwrite,
                    process_videos=process_videos
                )
                futures.append(future)
            elif 'ilias.php?baseClass=ilrepositorygui' in href:
                print(f"Link {href} is a folder")
                download_folder_files(session, href, download_dir, max_size, overwrite, max_workers)
        
        # Wait for all downloads to complete
        for future in futures:
            future.result()

# Main function to initiate download
def download_ilias_module(ilias_url, cookies, download_dir, max_size=None, overwrite=False, max_workers=3, process_videos=True):
    # Extract ref_id from URL
    parsed_url = urllib.parse.urlparse(ilias_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    ref_id = query_params.get('ref_id', ['unknown'])[0]
    
    # Setup logging before creating ref_id subfolder
    log_file = os.path.join(download_dir, f'download_ref{ref_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    
    # Create specific folder for this ref_id
    download_dir = os.path.join(download_dir, f'ref_{ref_id}')
    os.makedirs(download_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    start_time = datetime.now()
    session = create_session(cookies)
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    logging.info(f"Starting download from {ilias_url}")
    download_folder_files(session, ilias_url, download_dir, max_size, overwrite, max_workers)
    
    end_time = datetime.now()
    duration = end_time - start_time
    logging.info(f"Download completed in {duration}")

def load_cookies_from_file(cookie_file):
    try:
        with open(cookie_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading cookies from {cookie_file}: {str(e)}")
        return None

def main():
    # Create downloads and logs directories at startup
    downloads_dir = 'downloads'
    logs_dir = os.path.join(downloads_dir, 'logs')
    os.makedirs(downloads_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    parser = argparse.ArgumentParser(description='Download files from ILIAS platform')
    parser.add_argument('url', help='ILIAS module URL')
    parser.add_argument('-d', '--directory', default=downloads_dir,
                      help='Download directory (default: downloads)')
    parser.add_argument('-c', '--cookies', default='cookies.json',
                      help='Path to JSON file containing cookies (default: cookies.json)')
    parser.add_argument('-m', '--max-size', type=float,
                      help='Maximum file size in MB (e.g., 100.5)')
    parser.add_argument('-o', '--overwrite', action='store_true',
                      help='Overwrite existing files (default: skip existing)')
    parser.add_argument('-w', '--workers', type=int, default=3,
                      help='Number of parallel downloads (default: 3)')
    parser.add_argument('--keep-video-fps', action='store_true',
                      help='Keep original video FPS (default: convert to 1 FPS)')
    
    args = parser.parse_args()
    
    # Load cookies from file
    cookies = load_cookies_from_file(args.cookies)
    if not cookies:
        return
    
    try:
        print(f"Starting download from {args.url}")
        print(f"Files will be saved to: {args.directory}")
        download_ilias_module(
            args.url, 
            cookies, 
            args.directory,
            max_size=args.max_size,
            overwrite=args.overwrite,
            max_workers=args.workers,
            process_videos=not args.keep_video_fps
        )
        print("\nDownload completed successfully!")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")

if __name__ == "__main__":
    main()
