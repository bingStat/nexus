$tcIP = "100.103.12.14"
$n1IP = "192.168.31.88"
$token = "eyJhIjoiMjIyZmZlOTE2ZGIxMTU1MTAyYTQ1ZTRjZmI0YTRlYzgiLCJ0IjoiOGZiNGE4YzMtNzg3NC00NTBiLTg2NjEtZmFkNTJjNjRlNDk3IiwicyI6Ik5XSmhabVJoTVRBdFpHUmhaUzAwT1RnekxXSmlaVE10TURsbE5tVTNNMk5qWTJGayJ9"

$sshCmd = "scp -o StrictHostKeyChecking=no ~/cloudflared root@${n1IP}:/tmp/cloudflared && ssh -o StrictHostKeyChecking=no root@${n1IP} 'chmod +x /tmp/cloudflared && cp /tmp/cloudflared /usr/bin/cloudflared 2>/dev/null || (mkdir -p /opt/bin && cp /tmp/cloudflared /opt/bin/cloudflared); /opt/bin/cloudflared service install $token || /usr/bin/cloudflared service install $token'"

Write-Host "Running SSH to ThinkCenter..."
ssh -o StrictHostKeyChecking=no bing@$tcIP $sshCmd
