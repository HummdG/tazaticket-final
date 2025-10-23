# Project Documentation

## Overview
This document provides essential information about the Tazaticket project, including setup instructions, dependencies, and usage guidelines.

## Project Structure
```
tazaticket/
├── app/              # Main application code
│   ├── langgraph/    # LangGraph related components
│   ├── payloads/     # Data payload definitions
│   ├── services/     # Core services
│   ├── speech/       # Speech processing components
│   ├── statemachine/ # State machine implementations
│   └── tools/        # Utility tools
├── tests/            # Test files
├── main.py           # Entry point
├── requirements.txt  # Python dependencies
├── Dockerfile        # Docker configuration
└── docker-compose.yml # Docker Compose configuration
```

## Setup Instructions

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)

### Installation
1. Clone the repository
2. Navigate to the project directory
3. Conda envronment: All requirements are installed in `taza` conda environment. Activate it before running files and script and tests.
4. Install dependencies, if any are missing:
   ```bash
   pip install -r requirements.txt
   ```


### Running the Application
```bash
python main.py
```

## Docker Support
The project includes Docker configuration for containerized deployment:
- `Dockerfile`: Defines the application container
- `docker-compose.yml`: Orchestration for multi-container setups

To build and run with Docker:
```bash
docker-compose up --build
```

## Dependencies
Check `requirements.txt` for a complete list of Python dependencies.


## Testing
Tests are located in the `tests/` directory. Run them using:
```bash
python -m pytest tests/
```

