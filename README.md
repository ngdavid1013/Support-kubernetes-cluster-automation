# Kubernetes Cluster Automation Scripts

This repository contains Python scripts to automate Kubernetes cluster creation and configuration on different cloud providers.

---

## `support-eks-cluster.py`

This Python script automates the creation of an **Amazon EKS (Elastic Kubernetes Service)** cluster, configures networking, sets up worker nodes, installs the AWS EBS CSI driver addon, and optionally deploys Solace PubSub+ using Helm.

### Description

The script performs the following steps:

1.  **VPC Creation:** Creates a new VPC with a specified CIDR block.
2.  **Subnet Creation:** Creates public subnets in two Availability Zones within the VPC.
3.  **Internet Gateway & Routing:** Sets up an Internet Gateway and a Route Table to allow internet access for the subnets.
4.  **IAM Roles:** Creates the necessary IAM roles for the EKS cluster (`EKSClusterRole`) and worker nodes (`EKSNodeGroupRole`).
5.  **EKS Cluster Creation:** Provisions the EKS control plane.
6.  **Node Group Creation:** Creates a managed node group with EC2 instances based on user input (instance type, node count).
7.  **Kubeconfig Update:** Configures `kubectl` to connect to the newly created cluster.
8.  **EBS CSI Driver Addon:**
    *   Checks for and attempts to associate the required IAM OIDC provider for the cluster using `eksctl`.
    *   Creates the necessary IAM Role (`AmazonEKS_EBS_CSI_DriverRole_*`) with the correct trust policy for the driver's service account.
    *   Installs or updates the `aws-ebs-csi-driver` EKS managed addon using the AWS CLI.
    *   Verifies the driver's controller deployment is ready within Kubernetes using `kubectl`.
9.  **EBS StorageClass:** Creates a Kubernetes `StorageClass` named `ebs-sc` (using `gp2` volume type) provisioned by the EBS CSI driver.
10. **(Optional) Solace PubSub+ Deployment:** Deploys the Solace PubSub+ event broker using its Helm chart, configured to use the `ebs-sc` StorageClass for persistence. Allows specifying HA mode and optionally using an image from ECR.

### Prerequisites

Before running `support-eks-cluster.py`, ensure you have the following installed and configured:

1.  **Python 3:** The script is written in Python 3.
2.  **Python Modules:**
    *   `boto3`: The AWS SDK for Python (`pip install boto3`).
3.  **AWS CLI:** Installed and configured with appropriate AWS credentials (permissions to create VPC, EKS, IAM resources, EC2 instances, etc.).
4.  **`kubectl`:** The Kubernetes command-line tool.
5.  **`eksctl`:** Required for the automatic IAM OIDC provider association attempt. If not installed, the script will prompt for manual association if needed. ([Installation Guide](https://eksctl.io/installation/))
6.  **(Optional) Helm:** Required only if you choose to deploy Solace PubSub+. ([Installation Guide](https://helm.sh/docs/intro/install/))
7.  **(Optional) Docker:** Required only if deploying Solace using a custom image from ECR.

### Configuration

*   **AWS Credentials:** Ensure your AWS CLI is configured with credentials that have sufficient permissions. This is typically done using the `aws configure` command.
*   **AWS Region:** The script attempts to detect the AWS region automatically (from boto3 session, EC2 metadata). If detection fails, it will prompt the user.

### Usage

1.  Clone the repository (if you haven't already).
2.  Navigate to the repository directory in your terminal.
3.  Install the required Python module:
    ```bash
    pip install boto3
    ```
4.  Run the script:
    ```bash
    python support-eks-cluster.py
    ```
5.  Follow the interactive prompts to configure the cluster name, nodegroup name, instance type, and node scaling parameters. Default values are provided.
6.  The script will output the progress of each step.
7.  If the IAM OIDC provider is missing, the script will attempt to create it using `eksctl`. If `eksctl` is not found or fails, the script will exit with instructions for manual association.
8.  After cluster creation, you will be asked if you want to deploy Solace PubSub+.

### Notes

*   The script creates resources in your AWS account, which may incur costs.
*   Ensure you have the necessary permissions associated with your AWS credentials.
*   The EBS CSI driver setup relies on the EKS managed addon feature via the AWS CLI.
*   Error handling is included, but complex failures might require manual intervention via the AWS console or CLI.

---

## `support-cluster-creation.py`

This Python script automates the creation of Kubernetes clusters on **Microsoft Azure (AKS)** or **Google Cloud Platform (GKE)**, configures `kubectl`, and optionally deploys Solace PubSub+ using Helm.

### Description

The script performs the following steps:

1.  **Provider Selection:** Prompts the user to choose between Azure (AKS) and Google Cloud (GKE).
2.  **Cluster Creation:** Creates the Kubernetes cluster using the respective cloud provider's CLI (`az aks create` or `gcloud container clusters create`) based on user input (cluster name, resource group/zone, node count, VM size/machine type).
3.  **Kubeconfig Update:** Configures `kubectl` to connect to the newly created cluster using the provider's CLI (`az aks get-credentials` or `gcloud container clusters get-credentials`).
4.  **(Optional) Solace PubSub+ Deployment:** Deploys the Solace PubSub+ event broker using its Helm chart.
    *   Allows specifying HA mode.
    *   Optionally supports using a custom image from **AWS ECR**, handling ECR authentication and Kubernetes image pull secret creation (requires AWS credentials and `boto3`).

### Prerequisites

Before running `support-cluster-creation.py`, ensure you have the following installed and configured:

1.  **Python 3:** The script is written in Python 3.
2.  **Cloud Provider CLI:**
    *   **For Azure (AKS):** [Azure CLI (`az`)](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed and logged in (`az login`).
    *   **For Google Cloud (GKE):** [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed (Also elect to install the GKE authentication plugin: gke-gcloud-auth-plugin) and initialized (`gcloud init`).
3.  **`kubectl`:** The Kubernetes command-line tool.
4.  **(Optional) Helm:** Required only if you choose to deploy Solace PubSub+. ([Installation Guide](https://helm.sh/docs/intro/install/))
5.  **(Optional, for ECR):**
    *   **AWS CLI:** Installed and configured (`aws configure`) if using an ECR image.
    *   **`boto3`:** Python module (`pip install boto3`) if using an ECR image.
    *   **Docker:** Required if using an ECR image (for authentication testing).

### Configuration

*   **Cloud Provider Login:** Ensure you are logged into the respective cloud provider CLI (`az login` or `gcloud init`) with sufficient permissions to create Kubernetes clusters and related resources.
*   **(Optional, for ECR) AWS Account ID:** If using the ECR image option, the script currently has a hardcoded `AWS_ACCOUNT_ID` variable near the top. Verify this if necessary.
*   **(Optional, for ECR) AWS Credentials:** If using the ECR image option, ensure your AWS CLI is configured (`aws configure`) with credentials that have ECR access permissions.

### Usage

1.  Clone the repository (if you haven't already).
2.  Navigate to the repository directory in your terminal.
3.  Install `boto3` if planning to use the ECR option:
    ```bash
    pip install boto3
    ```
4.  Run the script:
    ```bash
    python support-cluster-creation.py
    ```
5.  Follow the interactive prompts to select the cloud provider and configure the cluster parameters.
6.  Choose whether to deploy Solace and if using an ECR image.
7.  The script will output the progress of each step.

### Notes

*   The script creates resources in your selected cloud provider account (Azure or GCP), which may incur costs.
*   Ensure you have the necessary permissions associated with your cloud provider login.
*   Error handling is included, but complex failures might require manual intervention via the cloud provider console or CLI.