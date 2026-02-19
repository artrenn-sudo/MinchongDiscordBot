$ProgressPreference = 'SilentlyContinue'
Write-Host "Downloading FFmpeg..."
Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile "ffmpeg.zip"
Write-Host "Extracting..."
Expand-Archive -Path "ffmpeg.zip" -DestinationPath "." -Force
Write-Host "Moving ffmpeg.exe..."
$folder = Get-ChildItem -Directory -Filter "ffmpeg-*-essentials_build"
Move-Item -Path "$($folder.FullName)\bin\ffmpeg.exe" -Destination "." -Force
Move-Item -Path "$($folder.FullName)\bin\ffprobe.exe" -Destination "." -Force
Remove-Item -Path "ffmpeg.zip" -Force
Remove-Item -Path "$($folder.FullName)" -Recurse -Force
Write-Host "Done! You can now run the bot."
