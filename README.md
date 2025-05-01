# EKS Cluster Creation and Configuration Script

This Python script automates the creation of an Amazon EKS (Elastic Kubernetes Service) cluster, configures networking, sets up worker nodes, installs the AWS EBS CSI driver addon, and optionally deploys Solace PubSub+ using Helm.

## Description

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

## Prerequisites

Before running the script, ensure you have the following installed and configured:

1.  **Python 3:** The script is written in Python 3.
2.  **Python Modules:**
    *   `boto3`: The AWS SDK for Python (`pip install boto3`).
3.  **AWS CLI:** Installed and configured with appropriate AWS credentials (permissions to create VPC, EKS, IAM resources, EC2 instances, etc.).
4.  **`kubectl`:** The Kubernetes command-line tool.
5.  **`eksctl`:** Required for the automatic IAM OIDC provider association attempt. If not installed, the script will prompt for manual association if needed. ([Installation Guide](https://eksctl.io/installation/))
6.  **(Optional) Helm:** Required only if you choose to deploy Solace PubSub+. ([Installation Guide](https://helm.sh/docs/intro/install/))
7.  **(Optional) Docker:** Required only if deploying Solace using a custom image from ECR.

## Configuration

*   **AWS Credentials:** Ensure your AWS CLI is configured with credentials that have sufficient permissions. This is typically done using the `aws configure` command.
*   **AWS Region:** The script attempts to detect the AWS region automatically (from boto3 session, EC2 metadata). If detection fails, it will prompt the user.

## Usage

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

## Notes

*   The script creates resources in your AWS account, which may incur costs.
*   Ensure you have the necessary permissions associated with your AWS credentials.
*   The EBS CSI driver setup relies on the EKS managed addon feature via the AWS CLI.
*   Error handling is included, but complex failures might require manual intervention via the AWS console or CLI.