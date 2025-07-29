#!/bin/bash

# LLM Kubernetes Setup Script für Ubuntu 24.04 LTS

# Installiert Docker, Kubernetes (kind), vLLM und Open WebUI

set -e

# Farben für Output

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
echo -e "${YELLOW}[WARNING] $1${NC}"
}

error() {
echo -e "${RED}[ERROR] $1${NC}"
exit 1
}

# Überprüfung der Systemvoraussetzungen

check_requirements() {
log "Überprüfe Systemvoraussetzungen…"

# Ubuntu Version prüfen
if ! grep -q "24.04" /etc/os-release; then
    warn "Dieses Script ist für Ubuntu 24.04 LTS optimiert"
fi

# Root-Rechte prüfen
if [[ $EUID -eq 0 ]]; then
    error "Bitte führen Sie dieses Script NICHT als root aus"
fi

# Speicherplatz prüfen (min. 50GB empfohlen)
available_space=$(df / | awk 'NR==2 {print $4}')
if [[ $available_space -lt 52428800 ]]; then
    warn "Weniger als 50GB freier Speicherplatz verfügbar. Empfohlen: mindestens 50GB"
fi

}

# System-Updates und Grundpakete

install_basics() {
log "System wird aktualisiert und Grundpakete installiert…"

sudo apt update
sudo apt upgrade -y
sudo apt install -y \
    curl \
    wget \
    git \
    unzip \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    apt-transport-https \
    jq \
    htop \
    nano \
    vim

}

# Docker Installation

install_docker() {
log "Docker wird installiert…"

# Alte Docker-Versionen entfernen
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Docker Repository hinzufügen
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker installieren
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# User zu docker Gruppe hinzufügen
sudo usermod -aG docker $USER

# Docker Service starten
sudo systemctl enable docker
sudo systemctl start docker

log "Docker erfolgreich installiert"

}

# Kubernetes (kind) Installation

install_kubernetes() {
log "Kubernetes (kind) wird installiert…"

# kubectl installieren
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# kind installieren
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Helm installieren
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
sudo apt update
sudo apt install -y helm

log "Kubernetes Tools erfolgreich installiert"

}

# Kind Cluster erstellen

create_kind_cluster() {
log "Kind Kubernetes Cluster wird erstellt…"

# Kind Cluster Config
cat > kind-config.yaml << EOF

kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: llm-cluster
nodes:

- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
    kubeletExtraArgs:
    node-labels: "ingress-ready=true"
    extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
  - containerPort: 30081
    hostPort: 30081
    protocol: TCP
- role: worker
  extraMounts:
  - hostPath: ./models
    containerPath: /models
    readOnly: false
    selinuxRelabel: false
    propagation: None
EOF
    
    # Models Verzeichnis erstellen
    
    mkdir -p ./models
    
    # Cluster erstellen
    
    kind create cluster -config=kind-config.yaml -wait=300s
    
    # NGINX Ingress Controller installieren
    
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
    kubectl wait -namespace ingress-nginx   
    -for=condition=ready pod   
    -selector=app.kubernetes.io/component=controller   
    -timeout=90s
    
    log "Kind Cluster erfolgreich erstellt"
    }

# vLLM Setup

setup_vllm() {
log "vLLM wird konfiguriert…"

# Namespace erstellen
kubectl create namespace vllm --dry-run=client -o yaml | kubectl apply -f -

# PersistentVolume für Models
cat > vllm-pv.yaml << EOF

## apiVersion: v1
kind: PersistentVolume
metadata:
name: model-storage
namespace: vllm
spec:
capacity:
storage: 100Gi
accessModes:
- ReadWriteMany
persistentVolumeReclaimPolicy: Retain
storageClassName: manual
hostPath:
path: /models

apiVersion: v1
kind: PersistentVolumeClaim
metadata:
name: model-storage-claim
namespace: vllm
spec:
accessModes:
- ReadWriteMany
resources:
requests:
storage: 100Gi
storageClassName: manual
EOF

kubectl apply -f vllm-pv.yaml

# vLLM Deployment mit mehreren Modellen
cat > vllm-deployment.yaml << EOF

## apiVersion: apps/v1
kind: Deployment
metadata:
name: vllm-llama-3-8b
namespace: vllm
spec:
replicas: 1
selector:
matchLabels:
app: vllm-llama-3-8b
template:
metadata:
labels:
app: vllm-llama-3-8b
spec:
containers:
- name: vllm
image: vllm/vllm-openai:latest
ports:
- containerPort: 8000
env:
- name: HUGGING_FACE_HUB_TOKEN
value: ""  # Optional: HuggingFace Token hier einfügen
command:
- python3
- -m
- vllm.entrypoints.openai.api_server
- -model
- meta-llama/Llama-3.2-3B-Instruct
- -host
- "0.0.0.0"
- -port
- "8000"
- -served-model-name
- llama-3.2-3b
- -max-model-len
- "4096"
- -tensor-parallel-size
- "1"
resources:
requests:
memory: "8Gi"
cpu: "2"
limits:
memory: "16Gi"
cpu: "4"
volumeMounts:
- name: model-storage
mountPath: /root/.cache/huggingface
- name: shm
mountPath: /dev/shm
volumes:
- name: model-storage
persistentVolumeClaim:
claimName: model-storage-claim
- name: shm
emptyDir:
medium: Memory
sizeLimit: 2Gi

apiVersion: v1
kind: Service
metadata:
name: vllm-llama-3-8b-service
namespace: vllm
spec:
selector:
app: vllm-llama-3-8b
ports:

- port: 8000
  targetPort: 8000
  nodePort: 30080
  type: NodePort

-----

## apiVersion: apps/v1
kind: Deployment
metadata:
name: vllm-mistral-7b
namespace: vllm
spec:
replicas: 1
selector:
matchLabels:
app: vllm-mistral-7b
template:
metadata:
labels:
app: vllm-mistral-7b
spec:
containers:
- name: vllm
image: vllm/vllm-openai:latest
ports:
- containerPort: 8001
env:
- name: HUGGING_FACE_HUB_TOKEN
value: ""  # Optional: HuggingFace Token hier einfügen
command:
- python3
- -m
- vllm.entrypoints.openai.api_server
- -model
- mistralai/Mistral-7B-Instruct-v0.3
- -host
- "0.0.0.0"
- -port
- "8001"
- -served-model-name
- mistral-7b
- -max-model-len
- "8192"
- -tensor-parallel-size
- "1"
resources:
requests:
memory: "8Gi"
cpu: "2"
limits:
memory: "16Gi"
cpu: "4"
volumeMounts:
- name: model-storage
mountPath: /root/.cache/huggingface
- name: shm
mountPath: /dev/shm
volumes:
- name: model-storage
persistentVolumeClaim:
claimName: model-storage-claim
- name: shm
emptyDir:
medium: Memory
sizeLimit: 2Gi

apiVersion: v1
kind: Service
metadata:
name: vllm-mistral-7b-service
namespace: vllm
spec:
selector:
app: vllm-mistral-7b
ports:

- port: 8001
  targetPort: 8001
  nodePort: 30081
  type: NodePort
EOF
  
  kubectl apply -f vllm-deployment.yaml
  
  log "vLLM Deployments erstellt"
  }

# Open WebUI Setup

setup_open_webui() {
log "Open WebUI wird installiert…"

# Helm Repository hinzufügen
helm repo add open-webui https://helm.openwebui.com/
helm repo update

# Namespace erstellen
kubectl create namespace open-webui --dry-run=client -o yaml | kubectl apply -f -

# Open WebUI Values
cat > open-webui-values.yaml << EOF

replicaCount: 1

image:
repository: ghcr.io/open-webui/open-webui
tag: main
pullPolicy: Always

service:
type: NodePort
port: 8080
nodePort: 30800

ingress:
enabled: true
className: "nginx"
annotations:
nginx.ingress.kubernetes.io/rewrite-target: /
hosts:
- host: open-webui.local
paths:
- path: /
pathType: Prefix

persistence:
enabled: true
storageClass: "manual"
accessModes:
- ReadWriteOnce
size: 10Gi

env:

- name: WEBUI_NAME
  value: "Local LLM Hub"
- name: OPENAI_API_BASE_URLS
  value: "http://vllm-llama-3-8b-service.vllm.svc.cluster.local:8000/v1,http://vllm-mistral-7b-service.vllm.svc.cluster.local:8001/v1"
- name: OPENAI_API_KEYS
  value: "sk-dummy-key,sk-dummy-key"

resources:
limits:
cpu: 1000m
memory: 2Gi
requests:
cpu: 500m
memory: 1Gi

nodeSelector: {}
tolerations: []
affinity: {}
EOF

# PV für Open WebUI
cat > open-webui-pv.yaml << EOF

apiVersion: v1
kind: PersistentVolume
metadata:
name: open-webui-storage
spec:
capacity:
storage: 10Gi
accessModes:
- ReadWriteOnce
persistentVolumeReclaimPolicy: Retain
storageClassName: manual
hostPath:
path: /tmp/open-webui
EOF

kubectl apply -f open-webui-pv.yaml

# Open WebUI installieren
helm upgrade --install open-webui open-webui/open-webui \
    --namespace open-webui \
    --values open-webui-values.yaml \
    --wait

log "Open WebUI erfolgreich installiert"

}

# Model Download Script erstellen

create_model_scripts() {
log "Model Download Scripts werden erstellt…"

cat > download-models.sh << 'EOF'

#!/bin/bash

# Model Download Script

# Lädt empfohlene Modelle für lokale Nutzung herunter

MODELS_DIR="./models"
mkdir -p $MODELS_DIR

echo "Downloadging models to $MODELS_DIR…"

# Kleinere, lokale Modelle für CPU/kleine GPU

models=(
"microsoft/DialoGPT-medium"
"microsoft/DialoGPT-small"
"google/flan-t5-base"
"google/flan-t5-small"
"stabilityai/stablelm-3b-4e1t"
)

for model in "${models[@]}"; do
echo "Downloading $model…"
cd $MODELS_DIR
git lfs install
git clone https://huggingface.co/$model
cd ..
done

echo "Model download completed!"
EOF

chmod +x download-models.sh

# Cloud API Konfiguration
cat > cloud-api-config.yaml << EOF

# Cloud API Konfiguration für Open WebUI

# OpenAI Configuration

openai:
api_key: "your-openai-api-key"
base_url: "https://api.openai.com/v1"
models:
- gpt-4
- gpt-3.5-turbo

# Anthropic Configuration

anthropic:
api_key: "your-anthropic-api-key"
base_url: "https://api.anthropic.com"
models:
- claude-3-sonnet
- claude-3-haiku

# Google Gemini Configuration

google:
api_key: "your-google-api-key"
base_url: "https://generativelanguage.googleapis.com/v1beta"
models:
- gemini-pro
- gemini-pro-vision

# Hinweis: API Keys in Open WebUI unter Settings > Connections konfigurieren

EOF

log "Model Scripts erstellt"

}

# Monitoring Setup

setup_monitoring() {
log "Monitoring wird eingerichtet…"

# Kubernetes Dashboard (optional)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml

# ServiceAccount für Dashboard
cat > dashboard-admin.yaml << EOF

## apiVersion: v1
kind: ServiceAccount
metadata:
name: admin-user
namespace: kubernetes-dashboard

apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
name: admin-user
roleRef:
apiGroup: rbac.authorization.k8s.io
kind: ClusterRole
name: cluster-admin
subjects:

- kind: ServiceAccount
  name: admin-user
  namespace: kubernetes-dashboard
EOF
  
  kubectl apply -f dashboard-admin.yaml
  
  log "Monitoring eingerichtet"
  }

# Status Check

check_status() {
log "Status wird überprüft…"

echo -e "\n${BLUE}=== Cluster Status ===${NC}"
kubectl get nodes

echo -e "\n${BLUE}=== vLLM Pods ===${NC}"
kubectl get pods -n vllm

echo -e "\n${BLUE}=== Open WebUI Pods ===${NC}"
kubectl get pods -n open-webui

echo -e "\n${BLUE}=== Services ===${NC}"
kubectl get svc --all-namespaces | grep -E "(vllm|open-webui)"

echo -e "\n${BLUE}=== Ingress ===${NC}"
kubectl get ingress --all-namespaces

}

# Cleanup Function

cleanup() {
warn "Cleanup wird ausgeführt…"
kind delete cluster -name llm-cluster 2>/dev/null || true
rm -f kind-config.yaml vllm-*.yaml open-webui-*.yaml dashboard-admin.yaml 2>/dev/null || true
}

# Abschluss-Informationen

print_info() {
log "Setup abgeschlossen!"

echo -e "\n${GREEN}=== Zugriff auf die Services ===${NC}"
echo -e "Open WebUI: http://localhost:30800"
echo -e "vLLM Llama-3.2-3B: http://localhost:30080"  
echo -e "vLLM Mistral-7B: http://localhost:30081"

echo -e "\n${GREEN}=== Nützliche Befehle ===${NC}"
echo -e "Status prüfen: kubectl get pods --all-namespaces"
echo -e "Logs anzeigen: kubectl logs -n vllm deployment/vllm-llama-3-8b"
echo -e "Port-Forward: kubectl port-forward -n open-webui svc/open-webui 8080:8080"
echo -e "Dashboard Token: kubectl -n kubernetes-dashboard create token admin-user"

echo -e "\n${GREEN}=== Weitere Schritte ===${NC}"
echo -e "1. Modelle herunterladen: ./download-models.sh"
echo -e "2. Cloud APIs in Open WebUI konfigurieren (Settings > Connections)"
echo -e "3. /etc/hosts bearbeiten: echo '127.0.0.1 open-webui.local' | sudo tee -a /etc/hosts"
echo -e "4. Für GPU-Support: NVIDIA Docker Runtime installieren"

echo -e "\n${YELLOW}Wichtige Hinweise:${NC}"
echo -e "- Neu einloggen für Docker-Gruppenmitgliedschaft"
echo -e "- Mindestens 16GB RAM für größere Modelle empfohlen"
echo -e "- Für Produktionsumgebung: SSL-Zertifikate und Authentifizierung konfigurieren"

}

# Main Execution

main() {
log "LLM Kubernetes Setup wird gestartet…"

check_requirements
install_basics
install_docker
install_kubernetes

# Neustart-Warnung für Docker-Gruppe
echo -e "\n${YELLOW}WICHTIG: Sie müssen sich neu einloggen oder 'newgrp docker' ausführen${NC}"
echo -e "${YELLOW}Drücken Sie Enter um fortzufahren...${NC}"
read -r

create_kind_cluster
setup_vllm
setup_open_webui
create_model_scripts
setup_monitoring

sleep 30  # Warten bis Pods bereit sind

check_status
print_info

log "Setup erfolgreich abgeschlossen!"

}

# Script mit Parametern ausführen

case "${1:-}" in
"cleanup")
cleanup
;;
"status")
check_status
;;
"")
main
;;
*)
echo "Usage: $0 [cleanup|status]"
exit 1
;;
esac
