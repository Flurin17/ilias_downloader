import os
from typing import List, Dict, Optional, Any, Union
from pathlib import Path
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
from datetime import datetime
from pathlib import Path

# Function to create a session with provided cookies
def create_session(cookies: List[Dict[str, str]]) -> requests.Session:
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])
    return session

# Function to sanitize filenames and directory names
def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

# Function to get the file name from the response headers
def get_filename_from_cd(cd: Optional[str]) -> Optional[str]:
    if not cd:
        return None
    fname = None
    if 'filename' in cd:
        fname = cd.split('filename=')[-1].strip().strip('"')
    return fname

# Function to download a file
def process_video(filepath: Union[str, Path], target_fps: int = 1) -> None:
    """Process video to change its FPS using ffmpeg"""
    try:
        filepath = Path(filepath)
        logging.info(f"Processing video: {filepath}")
        
        # Create a temporary file in the same directory with a simple name
        temp_dir = filepath.parent
        temp_name = f"temp_{filepath.stem}{filepath.suffix}"
        output_path = temp_dir / temp_name
        
        # Convert paths to strings with forward slashes
        input_path = str(filepath).replace('\\', '/')
        output_path_str = str(output_path).replace('\\', '/')
        
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
        
        logging.info(f"Converting to {target_fps} FPS...")
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
            logging.info("Video processing completed successfully")
        else:
            logging.error(f"Error processing video: {stderr}")
            if output_path.exists():
                output_path.unlink()
            raise Exception(f"ffmpeg failed with return code {process.returncode}")
            
    except Exception as e:
        logging.error(f"Error processing video {filepath}: {str(e)}")
        logging.error(f"Error processing video {filepath}: {str(e)}")

def download_file(
    session: requests.Session,
    file_url: str,
    download_dir: str,
    max_size: Optional[float] = None,
    overwrite: bool = False,
    max_retries: int = 3,
    process_videos: bool = True,
    skip_videos: bool = False
) -> bool:
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
        
        # Check if it's a video file
        mime_type = mimetypes.guess_type(download_path_with_extension)[0]
        if mime_type and mime_type.startswith('video'):
            if skip_videos:
                logging.info(f"Skipping video file: {filename}")
                os.remove(download_path_with_extension)
                return True
            elif process_videos:
                logging.info(f"Detected video file: {filename}")
                logging.info(f"MIME type: {mime_type}")
                process_video(download_path_with_extension)
        
        return True
    else:
        logging.error(f"Failed to download: {file_url} (Status code: {response.status_code})")
        return False

# Function to recursively download all files in a folder
def download_folder_files(
    session: requests.Session,
    folder_url: str,
    download_dir: str,
    max_size: Optional[float] = None,
    overwrite: bool = False,
    max_workers: int = 3,
    process_videos: bool = True,
    skip_videos: bool = False
) -> None:
    try:
        response = session.get(folder_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        })
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.ConnectionError as e:
        logging.error(f"Connection error while accessing {folder_url}: {str(e)}")
        if "Failed to resolve" in str(e):
            logging.error("DNS resolution failed. Please check your internet connection and the URL.")
        return
    except requests.exceptions.Timeout:
        logging.error(f"Timeout while accessing {folder_url}. Server is not responding.")
        return
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error occurred while accessing {folder_url}: {response.status_code} - {str(e)}")
        return
    except requests.exceptions.RequestException as e:
        logging.error(f"Error accessing {folder_url}: {str(e)}")
        return
    
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
                    process_videos=process_videos,
                    skip_videos=skip_videos
                )
                futures.append(future)
            elif 'ilias.php?baseClass=ilrepositorygui' in href:
                logging.info(f"Processing folder: {href}")
                download_folder_files(session, href, download_dir, max_size, overwrite, max_workers)
        
        # Wait for all downloads to complete
        for future in futures:
            future.result()

# Main function to initiate download
def download_ilias_module(
    ilias_url: str,
    cookies: List[Dict[str, str]],
    download_dir: str,
    max_size: Optional[float] = None,
    overwrite: bool = False,
    max_workers: int = 3,
    process_videos: bool = True,
    skip_videos: bool = False
) -> None:
    # Extract ref_id from URL
    parsed_url = urllib.parse.urlparse(ilias_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    ref_id = query_params.get('ref_id', ['unknown'])[0]
    
    # Create specific folder for this ref_id
    ref_download_dir = os.path.join(download_dir, f'ref_{ref_id}')
    log_dir = os.path.join(download_dir, "logs")
    os.makedirs(ref_download_dir, exist_ok=True)
    
    # Setup logging
    log_file = os.path.join(log_dir, f'download_ref{ref_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    
    # Remove any existing handlers to avoid duplicate logging
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
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
    download_folder_files(session, ilias_url, ref_download_dir, max_size, overwrite, max_workers, process_videos, skip_videos)
    
    end_time = datetime.now()
    duration = end_time - start_time
    logging.info(f"Download completed in {duration}")

def load_cookies_from_file(cookie_file: str) -> Optional[List[Dict[str, str]]]:
    try:
        with open(cookie_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Cookie file not found: {cookie_file}")
        return None
    except Exception as e:
        logging.error(f"Error loading cookies from {cookie_file}: {str(e)}")
        return None

def main() -> None:
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
    parser.add_argument('--no-video', action='store_true',
                      help='Skip downloading video files completely')
    
    args = parser.parse_args()
    

    cookies = load_cookies_from_file(args.cookies)
    if not cookies:
        return
    
    try:
        logging.info(f"Starting download from {args.url}")
        logging.info(f"Files will be saved to: {args.directory}")
        download_ilias_module(
            args.url, 
            cookies, 
            args.directory,
            max_size=args.max_size,
            overwrite=args.overwrite,
            max_workers=args.workers,
            process_videos=not args.keep_video_fps,
            skip_videos=args.no_video
        )
        logging.info("Download completed successfully!")
    except requests.exceptions.ConnectionError as e:
        logging.error(f"Connection error: {str(e)}")
        if "Failed to resolve" in str(e):
            logging.error("DNS resolution failed. Please check:")
            logging.error("1. Your internet connection")
            logging.error("2. VPN connection if required")
            logging.error("3. The URL is correct")
    except requests.exceptions.Timeout:
        logging.error("The request timed out. The server is not responding.")
        logging.error("Try again later or with fewer parallel downloads (-w option)")
    except requests.exceptions.TooManyRedirects:
        logging.error("Too many redirects. The URL might be incorrect or your cookies may have expired.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error occurred: {str(e)}")
        logging.error("Please check your internet connection and try again.")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")
        logging.error("If this persists, please report this issue with the error details.")

if __name__ == "__main__":
    main()
