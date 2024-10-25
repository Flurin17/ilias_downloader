import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import mimetypes
import re
import argparse
import json
from tqdm import tqdm

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
def download_file(session, file_url, download_dir):
    response = session.get(file_url, stream=True, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    })
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
        
        # Get file size for progress bar
        total_size = int(response.headers.get('content-length', 0))
        
        with tqdm(total=total_size, unit='iB', unit_scale=True, desc=filename) as pbar:
            with open(download_path_with_extension, 'wb') as file:
                for chunk in response.iter_content(1024):
                    size = file.write(chunk)
                    pbar.update(size)
        return True
    else:
        print(f"Failed to download: {file_url} (Status code: {response.status_code})")
        return False

# Function to recursively download all files in a folder
def download_folder_files(session, folder_url, download_dir):
    response = session.get(folder_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    })
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Find all links to files and subfolders
    for link in soup.find_all('a', href=True, class_="il_ContainerItemTitle"):
        href = link['href']
        href = urllib.parse.urljoin(folder_url, href)

        # Check if the link is a file or a folder
        if 'goto.php?target=file_' in href:
            print(f"Link {href} is a file")
            download_file(session, href, download_dir)

        elif 'ilias.php?baseClass=ilrepositorygui' in href:
            print(f"Link {href} is a folder")
            download_folder_files(session, href, download_dir)

# Main function to initiate download
def download_ilias_module(ilias_url, cookies, download_dir):
    session = create_session(cookies)
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    download_folder_files(session, ilias_url, download_dir)

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
    parser.add_argument('-c', '--cookies', required=True,
                      help='Path to JSON file containing cookies')
    
    args = parser.parse_args()
    
    # Load cookies from file
    cookies = load_cookies_from_file(args.cookies)
    if not cookies:
        return
    
    try:
        print(f"Starting download from {args.url}")
        print(f"Files will be saved to: {args.directory}")
        download_ilias_module(args.url, cookies, args.directory)
        print("\nDownload completed successfully!")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")

if __name__ == "__main__":
    main()
