from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct


class AiModelStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, description="Ec2 instaance for model", **kwargs)


        self.model_ec2_security_group = ec2.SecurityGroup(self, f"{environment}-ModelEc2SecurityGroup",
            vpc=vpc,
            security_group_name=f"{environment}-model-ec2-sg",
            description="Security group for Model EC2"
        )

        self.model_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(22),
            description="Allow SSH access from private subnets"
        )

        self.model_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(8080),
            description="Allow access to model from private subnets"
        )

        self.model_ec2_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(8081),
            description="Allow access to embedding model from private subnets"
        )

        self.model_ec2_instance = ec2.Instance(self, f"{environment}-ModelEc2Instance",
            instance_type=ec2.InstanceType("g4dn.2xlarge"),  # Choose an appropriate instance type for your model
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            instance_name=f"{environment}-llama-model",
            block_devices=[ec2.BlockDevice(
                device_name="/dev/xvda",
                volume=ec2.BlockDeviceVolume.ebs(50)  # 50 GB EBS volume
            )],
            vpc=vpc,
            security_group=self.model_ec2_security_group,
            user_data=ec2.UserData.custom('''
#!/bin/bash

set -e

sudo dnf clean all
sudo dnf install -y dkms

K_VER=$(uname -r)
K_MAJOR_VER=$(echo $K_VER | cut -d. -f1-2)
case $K_VER in
  6.1.*)
    sudo dnf install -y kernel-headers-$(uname -r) kernel-devel-$(uname -r) --allowerasing
    sudo dnf install -y kernel-modules-extra-$(uname -r) --allowerasing
    ;;
  *)
    sudo dnf install -y kernel$K_MAJOR_VER-headers-$(uname -r) kernel$K_MAJOR_VER-devel-$(uname -r) --allowerasing
    sudo dnf install -y kernel$K_MAJOR_VER-modules-extra-$(uname -r) --allowerasing
    ;;
esac

sudo dnf clean all

cd /tmp

sudo dnf install -y nvidia-release
sudo dnf clean expire-cache

sudo dnf install -y nvidia-open
sudo dnf install -y nvidia-xconfig
sudo dnf install -y cmake git openssl-devel


USER=ec2-user

sudo dnf install -y cuda-toolkit
sed -i '$aexport PATH=$PATH:/usr/local/cuda/bin' /home/$USER/.bashrc
sed -i '$aexport LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda/lib64' /home/$USER/.bashrc

sudo dnf install -y docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

sudo dnf install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo latest | sudo tee /etc/dnf/vars/releasever

if ( ec2-metadata -t | grep -q " p[0-9]" ); then
  sudo dnf install -y nvidia-fabricmanager libnvidia-nscq libnvsdm nvidia-imex
  if ( ec2-metadata -t | grep -q " p[6-9]" ); then
    sudo dnf install -y nvlsm nvlink5
    echo "ib_umad" | sudo tee -a /etc/modules-load.d/modules.conf
    sudo modprobe ib_umad
  fi
  sudo systemctl enable --now nvidia-fabricmanager
fi

# ============================================================
# Hugging Face CLI
# ============================================================

sudo dnf install -y python3.12 python3.12-pip

sudo -u "$USER" python3.12 -m venv /home/$USER/hf-venv

sudo -u "$USER" /home/$USER/hf-venv/bin/pip install --upgrade pip

sudo -u "$USER" /home/$USER/hf-venv/bin/pip install --upgrade huggingface_hub

if [ ! -x "/home/$USER/hf-venv/bin/hf" ]; then
    echo "ERROR: Hugging Face CLI was not installed"
    exit 1
fi

sudo -u "$USER" /home/$USER/hf-venv/bin/hf --version



# ============================================================
# llama.cpp
# ============================================================

LLAMA_DIR="/home/$USER/llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
    sudo -u "$USER" git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi
sudo chown -R "$USER:$USER" "$LLAMA_DIR"



# This portion runs after reboot

# ============================================================
# llama.cpp build script
# ============================================================
sudo tee /usr/local/bin/build-llama.sh > /dev/null <<'EOF'
#!/bin/bash

set -euo pipefail

USER="ec2-user"
LLAMA_DIR="/home/${USER}/llama.cpp"

mkdir -p /home/${USER}/models

echo "Waiting for NVIDIA driver..."

until nvidia-smi >/dev/null 2>&1; do
    echo "NVIDIA driver not ready..."
    sleep 5
done

echo "NVIDIA driver is ready"

echo "CUDA:"
nvcc --version

echo "GPU:"
nvidia-smi

cd "$LLAMA_DIR"

if [ -x "$LLAMA_DIR/build/bin/llama-server" ]; then
    echo "llama-server already built. Skipping rebuild."
    exit 0
fi

echo "Removing previous build..."
rm -rf build

echo "Configuring llama.cpp with CUDA..."

cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75

echo "Building llama.cpp..."

cmake --build build --config Release -j"$(nproc)"

EOF

sudo chmod +x /usr/local/bin/build-llama.sh

# ============================================================
# llama build systemd service
# ============================================================
sudo tee /etc/systemd/system/llama-build.service > /dev/null <<'EOF'
[Unit]
Description=llama.cpp CUDA Build
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ec2-user

Environment="PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda/lib64"

ExecStart=/usr/local/bin/build-llama.sh

RemainAfterExit=yes

EOF


# ============================================================
# llama model download script
# ============================================================
sudo tee /usr/local/bin/download-llama-model.sh > /dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
USER="ec2-user"
MODEL_DIR="/home/${USER}/models/Llama-3.1-8B-Instruct"
HF="/home/ec2-user/hf-venv/bin/hf"
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_DIR/Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf" ]; then
    echo "Downloading Llama 3.1 8B model..."
    $HF download \
        bartowski/Meta-Llama-3.1-8B-Instruct-GGUF \
        Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf \
        --local-dir "$MODEL_DIR"
else
    echo "Llama model already exists. Skipping download."
fi
EOF

sudo chmod +x /usr/local/bin/download-llama-model.sh

# ============================================================
# llama model download systemd service
# ============================================================
sudo tee /etc/systemd/system/llama-download.service > /dev/null <<'EOF'
[Unit]
Description=Download Llama 3.1 model
Requires=llama-build.service
After=llama-build.service
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ec2-user


Environment="PATH=/home/ec2-user/.local/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda/lib64"

ExecStart=/usr/local/bin/download-llama-model.sh

RemainAfterExit=yes

EOF


# ============================================================
# Download embedding model script
# ============================================================
sudo tee /usr/local/bin/download-nomic-embed.sh > /dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
USER="ec2-user"
MODEL_DIR="/home/${USER}/models/nomic-embed"
HF="/home/ec2-user/hf-venv/bin/hf"
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_DIR/nomic-embed-text-v1.5.Q4_K_M.gguf" ]; then
    echo "Downloading embedding model..."
    $HF download \
        nomic-ai/nomic-embed-text-v1.5-GGUF \
        nomic-embed-text-v1.5.Q4_K_M.gguf \
        --local-dir "$MODEL_DIR"
else
    echo "Embedding model already exists. Skipping download."
fi
EOF

sudo chmod +x /usr/local/bin/download-nomic-embed.sh

# ============================================================
# embedding model download systemd service
# ============================================================
sudo tee /etc/systemd/system/nomic-embed-download.service > /dev/null <<'EOF'
[Unit]
Description=download nomic-embed model
Requires=llama-build.service
After=llama-build.service
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=ec2-user

Environment="PATH=/home/ec2-user/.local/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda/lib64"

ExecStart=/usr/local/bin/download-nomic-embed.sh

RemainAfterExit=yes

EOF


# ============================================================
# llama31 server systemd service
# ============================================================
sudo tee /etc/systemd/system/llama-server.service > /dev/null <<'EOF'
[Unit]
Description=Llama 3.1 model server
Requires=llama-download.service
After=llama-download.service

[Service]
Type=simple
User=ec2-user

Environment="PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda/lib64"

ExecStart=/home/ec2-user/llama.cpp/build/bin/llama-server \
    --model /home/ec2-user/models/Llama-3.1-8B-Instruct/Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf \
    --alias llama31 \
    -t 4 \
    -tb 8 \
    -fa on \
    --numa distribute \
    -c 4096 \
    --host 0.0.0.0 \
    --port 8080

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

EOF


# ============================================================
# embedding server systemd service
# ============================================================
sudo tee /etc/systemd/system/nomic-embed-server.service > /dev/null <<'EOF'
[Unit]
Description=Nomic Embed model server
Requires=nomic-embed-download.service
After=nomic-embed-download.service

[Service]
Type=simple
User=ec2-user

Environment="PATH=/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
Environment="LD_LIBRARY_PATH=/usr/local/cuda/lib64"

ExecStart=/home/ec2-user/llama.cpp/build/bin/llama-server \
    --model /home/ec2-user/models/nomic-embed/nomic-embed-text-v1.5.Q4_K_M.gguf \
    --alias nomic-embed \
    --embedding \
    -t 1 \
    --host 0.0.0.0 \
    --port 8081

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

EOF


echo "=========================================="
echo "Final provisioning verification"
echo "=========================================="

command -v nvidia-smi
command -v nvcc
command -v cmake
command -v git
command -v docker
command -v python3.12

/home/ec2-user/hf-venv/bin/hf --version

test -d /home/ec2-user/llama.cpp
test -f /usr/local/bin/build-llama.sh
test -f /usr/local/bin/download-llama-model.sh
test -f /usr/local/bin/download-nomic-embed.sh

systemctl daemon-reload

echo "All userdata provisioning steps completed successfully."

sudo touch /var/lib/ec2-provisioning-complete

sudo systemctl enable llama-server.service
sudo systemctl enable nomic-embed-server.service

echo "Rebooting..."
sudo reboot''')       
)

        CfnOutput(self, f"{environment}-ModelEc2InstancePrivateDnsName", 
                  value=self.model_ec2_instance.instance_private_dns_name,
                  description="The private DNS name of the Model EC2 instance")
        CfnOutput(self, f"{environment}-ModelEc2InstancePrivateIp",
                  value=self.model_ec2_instance.instance_private_ip,
                  description="The private IP address of the Model EC2 instance") 

    @property
    def model_info(self) -> dict:
        return {
            "model-dns": self.model_ec2_instance.instance_private_dns_name,
            "model-ip": self.model_ec2_instance.instance_private_ip,
            "model-sg-id": self.model_ec2_security_group.security_group_id
        }

    