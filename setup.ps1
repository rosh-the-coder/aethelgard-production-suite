# Windows PowerShell Setup Script for Artwork Orchestrator and Etsy Pipeline

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Etsy Automated Pipeline Windows Setup   " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Current Directory: $PWD"
Write-Host

$venvPath = "tooling/ad-creatives/.venv"
$upscaleDir = "tooling/upscale"
$realesrganVer = "20220424"
$realesrganUrl = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-$realesrganVer-windows.zip"
$envFile = "$env:USERPROFILE\.config\ai-images\env"

# 1. Check Python
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "Found Python: $pyVersion"
} catch {
    Write-Error "Python is not installed or not in system PATH. Please install Python 3.10+ and restart."
}
Write-Host

# 2. Create Python virtual environment
Write-Host "[2/6] Creating virtual environment at $venvPath..." -ForegroundColor Yellow
if (Test-Path $venvPath) {
    Write-Host "Virtual environment already exists. Skipping creation."
} else {
    python -m venv $venvPath
    Write-Host "Virtual environment created."
}

Write-Host "Upgrading pip and installing Python dependencies..."
& "$venvPath/Scripts/pip.exe" install --quiet --upgrade pip
& "$venvPath/Scripts/pip.exe" install --quiet -r requirements.txt
& "$venvPath/Scripts/pip.exe" install --quiet playwright
Write-Host "Dependencies installed successfully."
Write-Host

# 3. Download Real-ESRGAN upscaler
Write-Host "[3/6] Fetching Real-ESRGAN upscaler for Windows..." -ForegroundColor Yellow
$binFile = "$upscaleDir/realesrgan-ncnn-vulkan.exe"
if (Test-Path $binFile) {
    Write-Host "Upscaler already exists at $binFile. Skipping download."
} else {
    if (-not (Test-Path $upscaleDir)) {
        New-Item -ItemType Directory -Path $upscaleDir -Force | Out-Null
    }
    
    $tempZip = [System.IO.Path]::GetTempFileName() + ".zip"
    Write-Host "Downloading Real-ESRGAN..."
    Invoke-WebRequest -Uri $realesrganUrl -OutFile $tempZip
    
    Write-Host "Extracting to $upscaleDir..."
    # Expand-Archive requires the folder to exist or creates it.
    Expand-Archive -Path $tempZip -DestinationPath $upscaleDir -Force
    
    # Check if there is a nested folder, if so move contents up
    $nestedFolder = Get-ChildItem -Path $upscaleDir -Directory | Select-Object -First 1
    if ($nestedFolder -and (Test-Path "$upscaleDir\$nestedFolder\realesrgan-ncnn-vulkan.exe")) {
        Write-Host "Moving files from nested folder..."
        Move-Item -Path "$upscaleDir\$nestedFolder\*" -Destination $upscaleDir -Force
        Remove-Item -Path "$upscaleDir\$nestedFolder" -Recurse -Force
    }
    
    # Clean up temp zip
    if (Test-Path $tempZip) { Remove-Item -Path $tempZip -Force }
    Write-Host "Upscaler installed successfully."
}
Write-Host

# 4. Initialize Playwright Browser
Write-Host "[4/6] Installing Playwright Chromium browser..." -ForegroundColor Yellow
& "$venvPath/Scripts/playwright.exe" install chromium
Write-Host "Playwright setup complete."
Write-Host

# 5. Create Key Scaffold
Write-Host "[5/6] Scaffolding API keys file at $envFile..." -ForegroundColor Yellow
if (Test-Path $envFile) {
    Write-Host "API key file already exists. Leaving it untouched."
} else {
    $parentDir = Split-Path -Path $envFile -Parent
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }
    
    $envContent = @"
# Artwork Orchestrator — your own API keys (this file is NOT shared).
# You only need GEMINI_API_KEY to run the default (Nano Banana) pipeline.
export GEMINI_API_KEY=""       # https://aistudio.google.com/apikey   (required)
export OPENAI_API_KEY=""       # https://platform.openai.com/api-keys (optional)
export OPENROUTER_API_KEY=""   # https://openrouter.ai/keys           (optional)
"@
    Set-Content -Path $envFile -Value $envContent
    Write-Host "Created empty key scaffold. Please fill in your API key(s) in $envFile."
}
Write-Host

# 6. Run Preflight
Write-Host "[6/6] Running preflight check..." -ForegroundColor Yellow
& "$venvPath/Scripts/python.exe" .claude/skills/artwork-orchestrator/scripts/artwork.py preflight
Write-Host

Write-Host "==========================================" -ForegroundColor Green
Write-Host "Setup Completed! Please configure your keys." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
