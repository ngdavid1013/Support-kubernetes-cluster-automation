import subprocess
import time
import json
import sys
import os
import boto3


# Function to execute shell commands
def run_command(command, exit_on_error=True, input_data=None, use_shell=None):
    is_list = isinstance(command, list)
    shell_mode = use_shell if use_shell is not None else not is_list # Default to shell=False if list, True if string, unless overridden
    
    print(f"Running: {' '.join(command) if is_list else command}")
    
    try:
        result = subprocess.run(
            command, shell=shell_mode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, input=input_data, check=False # check=False to handle errors manually
        )
    except FileNotFoundError:
        print(f"Error: Command not found. Ensure '{command[0] if is_list else command.split()[0]}' is in your PATH.")
        if exit_on_error:
            sys.exit(1)
        else:
            return None # Indicate failure

    if result.returncode != 0:
        cmd_str = ' '.join(command) if is_list else command
        print(f"Error executing command: {cmd_str}")
        print(f"Return Code: {result.returncode}")
        print(f"Stderr: {result.stderr}")
        print(f"Stdout: {result.stdout}") # Also print stdout for more context
        if exit_on_error:
            sys.exit(1)
        else:
            return None
    return result.stdout.strip()


# Default values
DEFAULT_NODE_COUNT = 3
DEFAULT_AKS_VM_SIZE = "Standard_DS2_v2"
DEFAULT_GKE_MACHINE_TYPE = "n2-standard-4"

# Function to validate input
def validate_name(name, resource_type):
    if not name or not name.strip():
        print(f"Error: {resource_type} name cannot be empty")
        return False
    return True

# Function to validate numeric input
def validate_number(value, min_val, max_val, name):
    try:
        num = int(value)
        if num < min_val or num > max_val:
            print(f"Error: {name} must be between {min_val} and {max_val}")
            return False
        return True
    except ValueError:
        print(f"Error: {name} must be a number")
        return False

# Function to create a Kubernetes cluster based on provider
def create_cluster(provider):
    location = None
    
    if provider == "aks":
        print("\n=== Azure Kubernetes Service (AKS) Configuration ===")
        
        # Get cluster name
        while True:
            cluster_name = input("Enter AKS cluster name: ").strip()
            if validate_name(cluster_name, "Cluster"):
                break
        
        # Get resource group
        while True:
            resource_group = input("Enter Azure resource group: ").strip()
            if validate_name(resource_group, "Resource group"):
                break
        
        # Get node count
        while True:
            node_count_input = input(f"Enter number of nodes (default: {DEFAULT_NODE_COUNT}): ").strip()
            if not node_count_input:
                node_count = DEFAULT_NODE_COUNT
                print(f"Using default node count: {node_count}")
                break
            if validate_number(node_count_input, 1, 10, "Node count"):
                node_count = int(node_count_input)
                break
        
        # Get VM size
        vm_size = input(f"Enter VM size (default: {DEFAULT_AKS_VM_SIZE}): ").strip()
        if not vm_size:
            vm_size = DEFAULT_AKS_VM_SIZE
            print(f"Using default VM size: {vm_size}")
        
        print(f"\nCreating AKS cluster '{cluster_name}' in resource group '{resource_group}'...")
        run_command(
            f"az aks create --resource-group {resource_group} "
            f"--name {cluster_name} "
            f"--node-count {node_count} "
            f"--vm-set-type VirtualMachineScaleSets "
            f"--node-vm-size {vm_size} "
            f"--enable-managed-identity "
            f"--generate-ssh-keys"
        )
        print("AKS cluster creation initiated...")
        location = resource_group  # For AKS, we'll use resource_group as the location

    elif provider == "gke":
        print("\n=== Google Kubernetes Engine (GKE) Configuration ===")
        
        # Get cluster name
        while True:
            cluster_name = input("Enter GKE cluster name: ").strip()
            if validate_name(cluster_name, "Cluster"):
                break
        
        # Get zone
        while True:
            zone = input("Enter GCP zone (e.g. us-central1-a): ").strip()
            if validate_name(zone, "Zone"):
                break
        
        # Get node count
        while True:
            node_count_input = input(f"Enter number of nodes (default: {DEFAULT_NODE_COUNT}): ").strip()
            if not node_count_input:
                node_count = DEFAULT_NODE_COUNT
                print(f"Using default node count: {node_count}")
                break
            if validate_number(node_count_input, 1, 10, "Node count"):
                node_count = int(node_count_input)
                break
        
        # Get machine type
        machine_type = input(f"Enter machine type (default: {DEFAULT_GKE_MACHINE_TYPE}): ").strip()
        if not machine_type:
            machine_type = DEFAULT_GKE_MACHINE_TYPE
            print(f"Using default machine type: {machine_type}")
        
        print(f"\nCreating GKE cluster '{cluster_name}' in zone '{zone}'...")
        run_command(
            f"gcloud container clusters create {cluster_name} "
            f"--num-nodes={node_count} "
            f"--zone {zone} "
            f"--machine-type={machine_type}"
        )
        print("GKE cluster creation initiated...")
        location = zone

    else:
        print("Invalid provider!")
        sys.exit(1)

    return cluster_name, location


# Function to configure kubectl
def configure_kubectl(provider, cluster_name, location=None):
    if provider == "aks":
        run_command(
            f"az aks get-credentials --resource-group {location} --name {cluster_name}"
        )
    elif provider == "gke":
        if location is None:
            print("Zone is required for GKE but not provided!")
            sys.exit(1)
        run_command(
            f"gcloud container clusters get-credentials {cluster_name} --zone {location}"
        )


# AWS Account ID - Hardcoded as per requirement
AWS_ACCOUNT_ID = "124361335672"

# Function to authenticate with AWS ECR and get login credentials
def authenticate_ecr(region):
    print("\n=== Authenticating with AWS ECR ===")
    
    try:
        # Use the hardcoded account ID
        account_id = AWS_ACCOUNT_ID
        
        # Get the ECR login token
        ecr_client = boto3.client('ecr', region_name=region)
        token = ecr_client.get_authorization_token()
        
        # Extract the registry URL
        registry_url = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
        
        print(f"Using ECR registry: {registry_url}")
        
        # Get auth token details
        auth_data = token['authorizationData'][0]
        auth_token = auth_data['authorizationToken']
        
        # Execute docker login
        run_command(f"aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry_url}")
        
        print("Successfully authenticated with ECR")
        return registry_url, auth_token
        
    except Exception as e:
        print(f"Error authenticating with ECR: {str(e)}")
        return None, None

# Function to create Kubernetes secret for ECR authentication
def create_ecr_pull_secret(region, namespace="default"):
    print(f"\n=== Creating Kubernetes secret for ECR in namespace '{namespace}' ===")
    
    try:
        # Get ECR password using AWS CLI
        ecr_password_cmd = ["aws", "ecr", "get-login-password", "--region", region]
        ecr_password = run_command(ecr_password_cmd, exit_on_error=True) # Use list for consistency
        if not ecr_password: # Check if password retrieval failed
             print("Error: Failed to retrieve ECR password.")
             return False
             
        registry_url = f"{AWS_ACCOUNT_ID}.dkr.ecr.{region}.amazonaws.com"

        # Create namespace if it doesn't exist (shell=True needed for pipe)
        ns_create_cmd = f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f -"
        run_command(ns_create_cmd, use_shell=True)

        # Delete existing secret if it exists
        delete_secret_cmd = ["kubectl", "delete", "secret", "ecr-secret", "-n", namespace, "--ignore-not-found"]
        run_command(delete_secret_cmd)

        # Create the secret using a list and shell=False
        secret_cmd_list = [
            "kubectl", "create", "secret", "docker-registry", "ecr-secret",
            f"--namespace={namespace}",
            f"--docker-server={registry_url}",
            f"--docker-username=AWS",
            f"--docker-email=no-reply@amazonaws.com",
            f"--docker-password={ecr_password}" # Pass password directly as argument
        ]

        # Execute the command with shell=False, passing password directly in args
        secret_creation_result_stdout = run_command(secret_cmd_list, exit_on_error=False, use_shell=False) # No input_data needed

        # Explicitly check if the secret command failed
        if not secret_creation_result_stdout or "created" not in secret_creation_result_stdout.lower():
             print(f"Error: 'kubectl create secret' command seems to have failed. Output: {secret_creation_result_stdout}")
             # Attempt to get logs or further details if possible, or just return False
             # For simplicity now, we'll just indicate failure
             return False # Indicate failure

        print("Secret creation command executed, adding a short delay before verification...")
        time.sleep(3) # Add a 3-second delay

        # Patch service account to use the secret
        patch_cmd = """
        kubectl patch serviceaccount default -n %s -p '{"imagePullSecrets": [{"name": "ecr-secret"}]}'
        """ % namespace
        run_command(patch_cmd)
        
        # Verify the secret and service account
        print("Verifying secret and service account configuration...")
        run_command(f"kubectl get secret ecr-secret -n {namespace} -o yaml")
        run_command(f"kubectl get serviceaccount default -n {namespace} -o yaml")
        
        # Test ECR access directly
        print("Testing ECR access...")
        test_cmd = f"docker pull {registry_url}/{AWS_ACCOUNT_ID}:latest || echo 'Repository may not exist, but credentials are working'"
        run_command(test_cmd, exit_on_error=False)
        
        print(f"ECR pull secret created in namespace '{namespace}'")
        return True
    except Exception as e:
        print(f"Error creating ECR pull secret: {str(e)}")
        return False

# Function to deploy Solace broker
def deploy_solace(ha_mode, use_ecr=False):
    print("\n=== Deploying Solace PubSub+ Broker ===")
    
    # Remove existing repository if it exists to avoid conflicts
    run_command("helm repo remove solacecharts", exit_on_error=False)
    
    # Add the Solace Helm chart repository
    run_command(
        "helm repo add solacecharts https://solaceproducts.github.io/pubsubplus-kubernetes-helm-quickstart/helm-charts"
    )
    run_command("helm repo update")
    
    # Prepare base Helm command
    helm_cmd = "helm install solace solacecharts/pubsubplus"
    
    # Configure redundancy based on HA mode and set admin password
    if ha_mode == "n":
        print("Deploying Solace in Standalone mode...")
        helm_cmd += " --set solace.redundancy=false,solace.usernameAdminPassword=admin"
    else:
        print("Deploying Solace in HA mode...")
        helm_cmd += " --set solace.redundancy=true,solace.usernameAdminPassword=admin"
    
    # If using ECR image
    if use_ecr:
        # Get ECR image details
        aws_region = input("Enter AWS region for ECR (e.g., us-east-1): ").strip()
        image_name = input("Enter ECR image name (e.g., solace-pubsub-enterprise): ").strip()
        image_tag = input("Enter image tag (e.g., 10.8.1.152): ").strip() or "latest"
        
        # Get namespace for Solace deployment
        namespace = input("Enter Kubernetes namespace for Solace deployment (default: default): ").strip() or "default"
        
        # Authenticate with ECR
        registry_url, auth_token = authenticate_ecr(aws_region)
        
        if registry_url:
            # Construct the full image URI
            image_uri = f"{registry_url}/{image_name}:{image_tag}"
            print(f"Using custom image: {image_uri}")
            
            # Create the ECR pull secret in the specified namespace
            secret_created = create_ecr_pull_secret(aws_region, namespace)
            
            if not secret_created:
                print("Failed to create ECR pull secret. Deployment may fail.")
            
            # Add the image to the Helm command (preserving the admin password setting)
            # Replace the existing --set with our new combined one
            helm_cmd = helm_cmd.replace(" --set solace.redundancy=false,solace.usernameAdminPassword=admin",
                                        f" --set solace.redundancy=false,solace.usernameAdminPassword=admin,image.repository={registry_url}/{image_name},image.tag={image_tag},image.pullSecretName=ecr-secret")
            helm_cmd = helm_cmd.replace(" --set solace.redundancy=true,solace.usernameAdminPassword=admin",
                                        f" --set solace.redundancy=true,solace.usernameAdminPassword=admin,image.repository={registry_url}/{image_name},image.tag={image_tag},image.pullSecretName=ecr-secret")
            
            # Add namespace to helm command if not default
            if namespace != "default":
                helm_cmd += f" --namespace {namespace} --create-namespace"
    
    # Execute the Helm command
    print(f"Running: {helm_cmd}")
    run_command(helm_cmd)
    
    print("\nSolace broker deployment initiated!")
    print("You can check the status with: kubectl get pods")


# Main script execution
if __name__ == "__main__":
    try:
        print("=== Kubernetes Cluster Creation Tool ===")
        print("This script helps you create a Kubernetes cluster and deploy Solace PubSub+")
        print(
            "\nSelect Cloud Provider: \n1. Azure (AKS) \n2. Google Cloud (GKE)"
        )
        
        choice = input("Enter choice (1/2): ")
        provider_map = {"1": "aks", "2": "gke"}
        provider = provider_map.get(choice)

        if not provider:
            print("Invalid choice!")
            sys.exit(1)

        print("\n=== Solace Deployment Configuration ===")
        while True:
            ha_mode = input("Do you want HA mode for Solace? (y/n): ").lower()
            if ha_mode in ["y", "n"]:
                break
            print("Please enter 'y' or 'n'")
            
        use_ecr = input("Do you want to use a Solace image from AWS ECR? (y/n): ").lower() == 'y'

        # Create the cluster
        cluster_name, location = create_cluster(provider)
        
        # Wait for user to continue
        input("\nPress Enter to continue with kubectl configuration and Solace deployment...")
        
        # Configure kubectl
        configure_kubectl(provider, cluster_name, location)
        
        # Deploy Solace
        deploy_solace(ha_mode, use_ecr)
        
        print("\n=== Deployment Complete! ===")
        print(f"Provider: {provider.upper()}")
        print(f"Cluster: {cluster_name}")
        print(f"Solace Mode: {'HA' if ha_mode == 'y' else 'Standalone'}")

        print("\n=== Next Steps ===")
        print("1. Wait for all pods to be in 'Running' state: kubectl get pods")
        print("2. For Solace admin access, run: kubectl get svc")
        print("   Look for the LoadBalancer external IP for the 'solace-pubsubplus' service")
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {str(e)}")
        sys.exit(1)
