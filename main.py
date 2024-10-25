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
def download_file(session, file_url, download_dir, max_size=None, overwrite=False, max_retries=3):
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
        return True
    else:
        print(f"Failed to download: {file_url} (Status code: {response.status_code})")
        return False

# Function to recursively download all files in a folder
def download_folder_files(session, folder_url, download_dir, max_size=None, overwrite=False, max_workers=3):
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
                    overwrite
                )
                futures.append(future)
            elif 'ilias.php?baseClass=ilrepositorygui' in href:
                print(f"Link {href} is a folder")
                download_folder_files(session, href, download_dir, max_size, overwrite, max_workers)
        
        # Wait for all downloads to complete
        for future in futures:
            future.result()

# Main function to initiate download
def download_ilias_module(ilias_url, cookies, download_dir, max_size=None, overwrite=False, max_workers=3):
    # Extract ref_id from URL
    parsed_url = urllib.parse.urlparse(ilias_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    ref_id = query_params.get('ref_id', ['unknown'])[0]
    
    # Create specific folder for this ref_id
    download_dir = os.path.join(download_dir, f'ref_{ref_id}')
    os.makedirs(download_dir, exist_ok=True)
    
    # Setup logging
    log_dir = os.path.join(download_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    # Configure logging with a Queue handler for thread safety
    log_queue = Queue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(queue_handler)
    
    # Create file and console handlers
    log_file = os.path.join(log_dir, f'download_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    handlers = [
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
    
    # Start queue listener
    listener = logging.handlers.QueueListener(log_queue, *handlers)
    listener.start()
    
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
    parser = argparse.ArgumentParser(description='Download files from ILIAS platform')
    parser.add_argument('url', help='ILIAS module URL')
    parser.add_argument('-d', '--directory', default='downloads',
                      help='Download directory (default: downloads)')
    parser.add_argument('-c', '--cookies', default='cookies.json',
                      help='Path to JSON file containing cookies (default: cookies.json)')
    parser.add_argument('-m', '--max-size', type=float,
                      help='Maximum file size in MB (e.g., 100.5)')
    parser.add_argument('-o', '--overwrite', action='store_true',
                      help='Overwrite existing files (default: skip existing)')
    parser.add_argument('-w', '--workers', type=int, default=3,
                      help='Number of parallel downloads (default: 3)')
    
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
            max_workers=args.workers
        )
        print("\nDownload completed successfully!")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")

if __name__ == "__main__":
    main()
