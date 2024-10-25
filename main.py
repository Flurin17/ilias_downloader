import os
import requests
from bs4 import BeautifulSoup
import urllib.parse
import mimetypes
import re

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
        
        with open(download_path_with_extension, 'wb') as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
        print(f"Downloaded: {download_path_with_extension}")
    else:
        print(f"Failed to download: {file_url}")

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

# Example usage
if __name__ == "__main__":
    ilias_url = "https://elearning.hslu.ch/ilias/ilias.php?baseClass=ilrepositorygui&cmd=view&ref_id=6189124"
    cookies = [
        {'name': 'PHPSESSID', 'value': 'a728b6cfe9edb2f005282fe1d8669c4e'},
        {'name': 'ilClientId', 'value': 'hslu'},
        # Add other necessary cookies here
    ]
    download_dir = "downloads/"
    
    download_ilias_module(ilias_url, cookies, download_dir)
