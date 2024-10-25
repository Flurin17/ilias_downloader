# ILIAS Downloader

A Python script to download files and folders from ILIAS learning management system.

## Features

- Downloads files and folders recursively from ILIAS
- Supports concurrent downloads for better performance
- Creates organized folder structure using ref_id
- Skips existing files by default
- Generates detailed logs for each download session
- Configurable file size limits
- Progress bars for download tracking

## Prerequisites

- Python 3.6 or higher
- Required Python packages:
  - requests
  - beautifulsoup4
  - tqdm

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/ilias_downloader.git
cd ilias_downloader
```

2. Install required packages:
```bash
pip install requests beautifulsoup4 tqdm moviepy
```

## Configuration

1. Create a `cookies.json` file with your ILIAS session cookies:
```json
[
    {
        "name": "PHPSESSID",
        "value": "your_php_session_id"
    },
    {
        "name": "ilClientId",
        "value": "your_client_id"
    }
]
```

## Usage

Basic usage:
```bash
python main.py "https://ilias.example.com/goto.php?target=crs_12345"
```

Advanced options:
```bash
python main.py "https://ilias.example.com/goto.php?target=crs_12345" \
    -d "custom_download_dir" \
    -c "path/to/cookies.json" \
    -m 100.5 \
    -w 5 \
    -o
```

### Command Line Arguments

- `url`: ILIAS module URL (required)
- `-d, --directory`: Download directory (default: "downloads")
- `-c, --cookies`: Path to cookies JSON file (default: "cookies.json")
- `-m, --max-size`: Maximum file size in MB (optional)
- `-w, --workers`: Number of parallel downloads (default: 3)
- `-o, --overwrite`: Overwrite existing files (default: skip existing)

## Output Structure

```
downloads/
├── download_ref12345_20240325_143022.log
└── ref_12345/
    ├── document1.pdf
    ├── document2.docx
    └── lecture_slides.pptx
```

## Logging

The script creates detailed logs for each download session in the download directory. Log files are named using the format: `download_ref{ref_id}_{timestamp}.log`

## License

This project is licensed under the MIT License - see the LICENSE file for details.
