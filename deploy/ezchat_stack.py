"""CDK stack for ezchat registry + lobby server on EC2."""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


USER_DATA = """\
#!/bin/bash
set -euo pipefail

# --- System setup ---
apt-get update -y
apt-get install -y git python3 python3-pip nginx certbot python3-certbot-nginx

# --- Install uv ---
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

# --- Clone ezchat ---
cd /opt
git clone https://github.com/wehale/ezchat.git
cd ezchat

# --- Create registry config ---
cat > registry.toml << 'REGEOF'
[registry]
host          = "127.0.0.1"
port          = 8080
heartbeat_ttl = 180
log_level     = "info"
REGEOF

# --- Create server config ---
TOKEN=$(openssl rand -hex 16)
DOMAIN="ezchat.kirbus.ai"

cat > server.toml << SRVEOF
[server]
host       = "0.0.0.0"
api_port   = 8000
relay_port = 9001
ttl        = 60
log_level  = "info"

[registry]
url         = "http://127.0.0.1:8080"
name        = "lobby"
description = "Public ezchat lobby"
secret      = "$TOKEN"
access      = "open"
public_url  = "http://$DOMAIN:8000"

[auth]
mode = "open"
SRVEOF

# --- Nginx reverse proxy for registry (HTTPS → localhost:8080) ---
cat > /etc/nginx/sites-available/ezchat << NGEOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
}
NGEOF

ln -sf /etc/nginx/sites-available/ezchat /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

# --- Create systemd services ---
cat > /etc/systemd/system/ezchat-registry.service << 'SVCEOF'
[Unit]
Description=ezchat registry
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ezchat
ExecStart=/root/.local/bin/uv run ezchat-registry --config registry.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/ezchat-server.service << 'SVCEOF'
[Unit]
Description=ezchat server
After=network.target ezchat-registry.service

[Service]
Type=simple
WorkingDirectory=/opt/ezchat
ExecStart=/root/.local/bin/uv run ezchat-server --config server.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# --- Start services ---
systemctl daemon-reload
systemctl enable ezchat-registry ezchat-server
systemctl start ezchat-registry
sleep 2
systemctl start ezchat-server

# --- TLS via certbot (runs after DNS is pointing here) ---
# Attempt certbot — will fail silently if DNS isn't ready yet.
# Re-run manually: certbot --nginx -d ezchat.kirbus.ai --non-interactive --agree-tos -m admin@kirbus.ai
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m admin@kirbus.ai || true
"""


class EzchatStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # --- VPC (default) ---
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # --- Security Group ---
        sg = ec2.SecurityGroup(self, "EzchatSG",
            vpc=vpc,
            description="ezchat registry + server",
            allow_all_outbound=True,
        )

        # SSH
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(22), "SSH")
        # Registry
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8080), "ezchat registry")
        # Rendezvous API
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8000), "ezchat rendezvous")
        # Relay
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(9001), "ezchat relay")
        # HTTP (for certbot later)
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "HTTP")
        # HTTPS (for future TLS)
        sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")

        # --- Key Pair ---
        # Uses an existing key pair — set via context:
        #   cdk deploy -c key_name=my-key
        key_name = self.node.try_get_context("key_name") or "ezchat-key"

        # --- EC2 Instance ---
        instance = ec2.Instance(self, "EzchatInstance",
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.from_ssm_parameter(
                "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id",
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=sg,
            key_pair=ec2.KeyPair.from_key_pair_name(self, "KeyPair", key_name),
            user_data=ec2.UserData.custom(USER_DATA),
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(20, volume_type=ec2.EbsDeviceVolumeType.GP3),
                )
            ],
        )

        # --- Elastic IP ---
        eip = ec2.CfnEIP(self, "EzchatEIP")
        ec2.CfnEIPAssociation(self, "EIPAssoc",
            eip=eip.ref,
            instance_id=instance.instance_id,
        )

        # --- Outputs ---
        CfnOutput(self, "PublicIP",
            value=eip.ref,
            description="Elastic IP — point ezchat.kirbus.ai DNS here",
        )
        CfnOutput(self, "RegistryURL",
            value=cdk.Fn.join("", ["http://", eip.ref, ":8080"]),
            description="Registry URL",
        )
        CfnOutput(self, "ServerURL",
            value=cdk.Fn.join("", ["http://", eip.ref, ":8000"]),
            description="Server URL",
        )
        CfnOutput(self, "SSH",
            value=cdk.Fn.join("", ["ssh -i ~/.ssh/", key_name, ".pem ubuntu@", eip.ref]),
            description="SSH command",
        )
