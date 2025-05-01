import boto3
import time
from botocore.exceptions import ClientError
import subprocess
import sys
import re
import json # Added import
import tempfile # Added import
import os # Added import
from pathlib import Path # Added import

# Initialize Boto3 clients
ec2 = boto3.client('ec2')
eks = boto3.client('eks')
iam = boto3.client('iam')

# Default values
DEFAULT_CLUSTER_NAME = 'pu-eks-cluster'
DEFAULT_NODEGROUP_NAME = 'eks-nodegroup'
DEFAULT_INSTANCE_TYPE = 't3.medium'
DEFAULT_MIN_NODES = 3
DEFAULT_MAX_NODES = 4
DEFAULT_DESIRED_NODES = 3

# Create VPC
def create_vpc():
    print("Creating VPC...")
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16', AmazonProvidedIpv6CidrBlock=False)
    vpc_id = vpc['Vpc']['VpcId']
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})
    ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
    print(f"VPC Created: {vpc_id}")
    return vpc_id

# Create Subnets in two AZs
def create_subnets(vpc_id):
    print("Creating Subnets in two AZs...")
    azs = ec2.describe_availability_zones()['AvailabilityZones']
    subnet_ids = []

    for i, az in enumerate(azs[:2]):  # Only select two AZs
        subnet = ec2.create_subnet(
            CidrBlock=f'10.0.{i}.0/24',
            VpcId=vpc_id,
            AvailabilityZone=az['ZoneName']
        )
        subnet_id = subnet['Subnet']['SubnetId']
        subnet_ids.append(subnet_id)

        # Enable auto-assign public IP for the subnet
        ec2.modify_subnet_attribute(
            SubnetId=subnet_id,
            MapPublicIpOnLaunch={'Value': True}
        )
        print(f"Subnet Created in {az['ZoneName']}: {subnet_id}")
    
    return subnet_ids

# Create Internet Gateway and Route Table
def create_internet_gateway(vpc_id):
    print("Creating Internet Gateway...")
    igw = ec2.create_internet_gateway()
    igw_id = igw['InternetGateway']['InternetGatewayId']
    ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
    print(f"Internet Gateway Created: {igw_id}")
    return igw_id

# Create Route Table and associate with subnets
def create_route_table(vpc_id, subnet_ids):
    print("Creating Route Table and associating to subnets...")
    route_table = ec2.create_route_table(VpcId=vpc_id)
    route_table_id = route_table['RouteTable']['RouteTableId']
    
    # Create a route to the Internet Gateway
    ec2.create_route(
        RouteTableId=route_table_id,
        DestinationCidrBlock='0.0.0.0/0',
        GatewayId=create_internet_gateway(vpc_id)
    )
    
    # Associate route table with subnets
    for subnet_id in subnet_ids:
        ec2.associate_route_table(SubnetId=subnet_id, RouteTableId=route_table_id)
        print(f"Associated Route Table {route_table_id} to Subnet {subnet_id}")

# Create IAM Roles if they don't exist
def create_iam_roles():
    print("Creating IAM roles if not existing...")

    try:
        # Create EKS Cluster Role
        cluster_role = iam.create_role(
            RoleName='EKSClusterRole',
            AssumeRolePolicyDocument='''{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "eks.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }]
            }'''
        )
        cluster_role_arn = cluster_role['Role']['Arn']
        print("IAM Role EKSClusterRole created.")
    except iam.exceptions.EntityAlreadyExistsException:
        cluster_role_arn = iam.get_role(RoleName='EKSClusterRole')['Role']['Arn']
        print("IAM Role EKSClusterRole already exists. Skipping creation.")

    try:
        # Create NodeGroup Role
        node_role = iam.create_role(
            RoleName='EKSNodeGroupRole',
            AssumeRolePolicyDocument='''{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "ec2.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }]
            }'''
        )
        node_role_arn = node_role['Role']['Arn']
        print("IAM Role EKSNodeGroupRole created.")
    except iam.exceptions.EntityAlreadyExistsException:
        node_role_arn = iam.get_role(RoleName='EKSNodeGroupRole')['Role']['Arn']
        print("IAM Role EKSNodeGroupRole already exists. Skipping creation.")

    return cluster_role_arn, node_role_arn

# Create EKS Cluster
def create_cluster(subnet_ids, cluster_role_arn, cluster_name):
    print(f"Creating EKS Cluster '{cluster_name}'...")
    response = eks.create_cluster(
        name=cluster_name,
        roleArn=cluster_role_arn,
        resourcesVpcConfig={
            'subnetIds': subnet_ids,
            'endpointPublicAccess': True,
            'endpointPrivateAccess': False
        }
    )
    print("EKS Cluster creation initiated...")

    # Wait for the cluster to become active
    waiter = eks.get_waiter('cluster_active')
    waiter.wait(name=cluster_name)
    print("EKS Cluster is now active.")
    return response

# Create Node Group
def create_nodegroup(subnet_ids, node_role_arn, cluster_name, nodegroup_name, instance_type, min_nodes, max_nodes, desired_nodes):
    print(f"Creating Node Group '{nodegroup_name}'...")
    response = eks.create_nodegroup(
        clusterName=cluster_name,
        nodegroupName=nodegroup_name,
        nodeRole=node_role_arn,
        subnets=subnet_ids,
        instanceTypes=[instance_type],
        scalingConfig={
            'minSize': min_nodes,
            'maxSize': max_nodes,
            'desiredSize': desired_nodes
        },
        diskSize=30
    )
    print("Node Group creation initiated...")

    # Wait for the nodegroup to be active
    waiter = eks.get_waiter('nodegroup_active')
    waiter.wait(clusterName=cluster_name, nodegroupName=nodegroup_name)
    print("Node Group created and active.")

# Update kubeconfig for kubectl
def update_kubeconfig(cluster_name):
    print(f"Configuring kubectl to access the EKS cluster '{cluster_name}'...")
    subprocess.run(['aws', 'eks', 'update-kubeconfig', '--name', cluster_name], check=True)
    print("Kubeconfig updated. You can now access the cluster with kubectl.")

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
        subprocess.run(
            f"aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry_url}",
            shell=True, check=True
        )
        
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
        result = subprocess.run(
            f"aws ecr get-login-password --region {region}",
            shell=True, check=True, stdout=subprocess.PIPE, text=True
        )
        ecr_password = result.stdout.strip()
        registry_url = f"{AWS_ACCOUNT_ID}.dkr.ecr.{region}.amazonaws.com"
        
        # Create namespace if it doesn't exist
        subprocess.run(
            f"kubectl create namespace {namespace} --dry-run=client -o yaml | kubectl apply -f -",
            shell=True, check=True
        )
        
        # Delete existing secret if it exists
        subprocess.run(
            f"kubectl delete secret ecr-secret -n {namespace} --ignore-not-found",
            shell=True, check=True
        )
        
        # Create the secret
        secret_cmd = f"""
        kubectl create secret docker-registry ecr-secret \\
          --namespace={namespace} \\
          --docker-server={registry_url} \\
          --docker-username=AWS \\
          --docker-password='{ecr_password}' \\
          --docker-email=no-reply@amazonaws.com
        """
        subprocess.run(secret_cmd, shell=True, check=True)
        
        # Patch service account to use the secret
        patch_cmd = f"""
        kubectl patch serviceaccount default -n {namespace} -p '{{"imagePullSecrets": [{{"name": "ecr-secret"}}]}}'
        """
        subprocess.run(patch_cmd, shell=True, check=True)
        
        # Verify the secret and service account
        print("Verifying secret and service account configuration...")
        subprocess.run(f"kubectl get secret ecr-secret -n {namespace} -o yaml", shell=True, check=True)
        subprocess.run(f"kubectl get serviceaccount default -n {namespace} -o yaml", shell=True, check=True)
        
        # Test ECR access directly
        print("Testing ECR access...")
        try:
            test_cmd = f"docker pull {registry_url}/{AWS_ACCOUNT_ID}:latest || echo 'Repository may not exist, but credentials are working'"
            subprocess.run(test_cmd, shell=True, check=False)
        except:
            print("Docker pull test failed, but this may be expected if the repository doesn't exist")
        
        print(f"ECR pull secret created in namespace '{namespace}'")
        return True
    except Exception as e:
        print(f"Error creating ECR pull secret: {str(e)}")
        return False

# (Function create_ebs_csi_iam_policy removed as it's no longer needed)

# Function to create IAM role for EBS CSI Driver using AWS CLI
def create_ebs_csi_iam_role(cluster_name, oidc_provider_url, region):
    print("\n=== Creating IAM role for EBS CSI Driver via AWS CLI ===")
    role_name = f"AmazonEKS_EBS_CSI_DriverRole_{cluster_name}"
    # Use the AWS Managed Policy ARN
    policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
    aws_account_id = AWS_ACCOUNT_ID # Assuming AWS_ACCOUNT_ID is defined globally

    try:
        # Check if role already exists
        get_role_cmd = f"aws iam get-role --role-name {role_name} --region {region}"
        print(f"Checking if role exists: {get_role_cmd}")
        result = subprocess.run(get_role_cmd, shell=True, check=True, capture_output=True, text=True)
        role_arn = json.loads(result.stdout)['Role']['Arn']
        print(f"IAM role {role_name} already exists with ARN: {role_arn}")
        # Ensure the policy is attached even if the role exists
        attach_policy_cmd = f"aws iam attach-role-policy --role-name {role_name} --policy-arn {policy_arn} --region {region}"
        print(f"Ensuring policy is attached: {attach_policy_cmd}")
        subprocess.run(attach_policy_cmd, shell=True, check=True)
        print(f"Managed policy {policy_arn} ensured on role {role_name}.")
        return role_arn

    except subprocess.CalledProcessError as e:
        if "NoSuchEntity" in e.stderr or "NoSuchEntityException" in e.stderr:
            print(f"IAM role {role_name} does not exist. Creating...")
            # Role doesn't exist, create it
            oidc_issuer_host = oidc_provider_url.replace('https://', '')

            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Federated": f"arn:aws:iam::{aws_account_id}:oidc-provider/{oidc_issuer_host}"
                        },
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                # This condition targets the specific service account used by the EBS CSI driver addon
                                f"{oidc_issuer_host}:sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa"
                            }
                        }
                    }
                ]
            }

            # Use a temporary file for the trust policy to avoid shell escaping issues
            trust_policy_json_str = json.dumps(trust_policy)
            temp_policy_file = None
            try:
                # Create the role using the temporary file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as tf:
                    tf.write(trust_policy_json_str)
                    temp_policy_file = tf.name
                
                # Construct file URI differently based on OS due to AWS CLI parsing issues on Windows
                if sys.platform == "win32":
                    # AWS CLI on Windows often prefers this non-standard format
                    policy_document_uri = f"file://{temp_policy_file}"
                else:
                    # Standard file URI format for Linux/macOS
                    policy_document_uri = f"file:///{temp_policy_file}"

                create_role_cmd = (
                    f"aws iam create-role --role-name {role_name} "
                    f"--assume-role-policy-document {policy_document_uri} "
                    f"--description \"IAM role for EBS CSI Driver on cluster {cluster_name}\" "
                    f"--region {region}"
                )
                print(f"Creating role using temporary policy file: {temp_policy_file}")
                print(f"Executing: {create_role_cmd}")

                result = subprocess.run(create_role_cmd, shell=True, check=True, capture_output=True, text=True)
                role_arn = json.loads(result.stdout)['Role']['Arn']
                print(f"IAM role {role_name} created with ARN: {role_arn}")

                # Attach the policy to the new role
                print(f"Waiting briefly before attaching policy...")
                time.sleep(10) # Add a small delay to allow role propagation

                attach_policy_cmd = f"aws iam attach-role-policy --role-name {role_name} --policy-arn {policy_arn} --region {region}"
                print(f"Attaching policy: {attach_policy_cmd}")
                subprocess.run(attach_policy_cmd, shell=True, check=True)
                print(f"Managed policy {policy_arn} attached to role {role_name}.")
                return role_arn

            except subprocess.CalledProcessError as create_err:
                print(f"Error creating IAM role or attaching policy: {create_err}")
                print(f"Stderr: {create_err.stderr}")
                return None
            except Exception as inner_e:
                 print(f"Error processing role creation: {str(inner_e)}")
                 return None
            finally:
                 # Clean up the temporary file
                 if temp_policy_file and os.path.exists(temp_policy_file):
                      try:
                           os.remove(temp_policy_file)
                           print(f"Removed temporary policy file: {temp_policy_file}")
                      except OSError as rm_err:
                           print(f"Warning: Could not remove temporary policy file {temp_policy_file}: {rm_err}")
        else:
            # Other error during get-role check
            print(f"Error checking IAM role: {e}")
            print(f"Stderr: {e.stderr}")
            return None
    except Exception as e:
        print(f"An unexpected error occurred in create_ebs_csi_iam_role: {str(e)}")
        return None


# Function to ensure EBS CSI driver is installed via EKS Addon using AWS CLI
def ensure_ebs_csi_driver(cluster_name):
    print("\n=== Ensuring EBS CSI Driver Addon via AWS CLI ===")
    addon_name = "aws-ebs-csi-driver"
    # Try to get region from the default boto3 session configuration
    session = boto3.session.Session()
    region = session.region_name

    if not region:
        # Fallback if region not found in default session config or environment variables
        print("AWS region not found in default session. Attempting to fetch from EC2 metadata...")
        try:
            # Attempt to get region from EC2 metadata service (if running on EC2)
            metadata_cmd = "curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | grep region | awk -F\\\" '{print $4}'"
            result = subprocess.run(metadata_cmd, shell=True, check=True, capture_output=True, text=True, timeout=5)
            region = result.stdout.strip()
            if not region:
                 raise ValueError("Region from metadata is empty")
            print(f"Using region from EC2 metadata: {region}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError) as meta_err:
            print(f"Could not get region from metadata ({meta_err}). Asking user...")
            region_input = input("Enter AWS region (e.g., us-east-1): ").strip()
            if not region_input:
                 print("Error: AWS Region is required.")
                 return False
            region = region_input
            print(f"Using user-provided region: {region}")


    try:
        # 1. Get Cluster OIDC Issuer URL
        print(f"Fetching OIDC issuer URL for cluster '{cluster_name}'...")
        describe_cluster_cmd = f"aws eks describe-cluster --name {cluster_name} --query cluster.identity.oidc.issuer --output text --region {region}"
        result = subprocess.run(describe_cluster_cmd, shell=True, check=True, capture_output=True, text=True)
        oidc_issuer_url = result.stdout.strip()
        if not oidc_issuer_url or oidc_issuer_url == "None":
            print(f"Error: Could not retrieve OIDC issuer URL for cluster '{cluster_name}'.")
            print("Attempting to associate OIDC provider using eksctl (requires eksctl to be installed)...")
            eksctl_cmd = f"eksctl utils associate-iam-oidc-provider --region {region} --cluster {cluster_name} --approve"
            try:
                 subprocess.run(eksctl_cmd, shell=True, check=True)
                 print("eksctl command succeeded. Retrying to fetch OIDC issuer URL...")
                 result = subprocess.run(describe_cluster_cmd, shell=True, check=True, capture_output=True, text=True)
                 oidc_issuer_url = result.stdout.strip()
                 if not oidc_issuer_url or oidc_issuer_url == "None":
                      print("Error: Still could not retrieve OIDC issuer URL after eksctl attempt.")
                      print("Please manually associate an IAM OIDC provider with your cluster.")
                      print(f"Example: eksctl utils associate-iam-oidc-provider --region {region} --cluster {cluster_name} --approve")
                      return False
            except (subprocess.CalledProcessError, FileNotFoundError) as eksctl_err:
                 print(f"Error running eksctl: {eksctl_err}")
                 print("Please manually associate an IAM OIDC provider with your cluster.")
                 print(f"Example: eksctl utils associate-iam-oidc-provider --region {region} --cluster {cluster_name} --approve")
                 print("Or use the AWS console/CLI: https://docs.aws.amazon.com/eks/latest/userguide/enable-iam-roles-for-service-accounts.html")
                 return False

        print(f"OIDC Issuer URL: {oidc_issuer_url}")
        oidc_issuer_host = oidc_issuer_url.replace('https://', '')

        # 2. Check if OIDC Provider Exists in IAM (Informational)
        print(f"Checking if IAM OIDC provider exists for {oidc_issuer_host}...")
        # Use appropriate command based on OS for searching string output
        check_oidc_cmd = f"aws iam list-open-id-connect-providers --region {region}"
        try:
            result = subprocess.run(check_oidc_cmd, shell=True, check=True, capture_output=True, text=True)
            if oidc_issuer_host not in result.stdout:
                 raise subprocess.CalledProcessError(1, check_oidc_cmd, output=result.stdout, stderr="Provider not found in list")
            print("IAM OIDC provider found.")
        except subprocess.CalledProcessError:
            print(f"IAM OIDC provider for {oidc_issuer_host} not found in AWS account {AWS_ACCOUNT_ID}.")
            print("Attempting to associate IAM OIDC provider using eksctl...")
            eksctl_associate_cmd = f"eksctl utils associate-iam-oidc-provider --region {region} --cluster {cluster_name} --approve"
            try:
                subprocess.run(eksctl_associate_cmd, shell=True, check=True, capture_output=True, text=True)
                print("Successfully associated IAM OIDC provider via eksctl.")
                # Allow script to continue after successful association
            except FileNotFoundError:
                print(f"Error: 'eksctl' command not found. Cannot automatically associate OIDC provider.")
                print(f"Please install eksctl or manually associate the provider for cluster '{cluster_name}' using AWS console/CLI.")
                print("Manual association instructions: https://docs.aws.amazon.com/eks/latest/userguide/enable-iam-roles-for-service-accounts.html")
                return False # Stop execution if eksctl is not found
            except subprocess.CalledProcessError as eksctl_err:
                print(f"Error running '{eksctl_associate_cmd}': {eksctl_err}")
                print(f"Stderr: {eksctl_err.stderr}")
                print(f"Please check eksctl logs or manually associate the provider for cluster '{cluster_name}' using AWS console/CLI.")
                print("Manual association instructions: https://docs.aws.amazon.com/eks/latest/userguide/enable-iam-roles-for-service-accounts.html")
                return False # Stop execution if association fails

        # 3. Create IAM Role for the EBS CSI Driver Service Account
        role_arn = create_ebs_csi_iam_role(cluster_name, oidc_issuer_url, region)
        if not role_arn:
            print("Failed to create or retrieve IAM role for EBS CSI Driver.")
            return False

        # 4. Check if Addon exists and create/update
        print(f"Checking status of EKS addon '{addon_name}'...")
        describe_addon_cmd = f"aws eks describe-addon --cluster-name {cluster_name} --addon-name {addon_name} --region {region}"
        try:
            result = subprocess.run(describe_addon_cmd, shell=True, check=True, capture_output=True, text=True)
            addon_info = json.loads(result.stdout)['addon']
            current_role_arn = addon_info.get('serviceAccountRoleArn')
            print(f"Addon '{addon_name}' found. Status: {addon_info['status']}, Current Role ARN: {current_role_arn}")

            if current_role_arn != role_arn:
                 print(f"Addon role ARN ({current_role_arn}) differs from expected ({role_arn}). Updating addon...")
                 # Using --resolve-conflicts OVERWRITE to force role update if needed
                 update_addon_cmd = (
                      f"aws eks update-addon --cluster-name {cluster_name} --addon-name {addon_name} "
                      f"--service-account-role-arn {role_arn} --resolve-conflicts OVERWRITE --region {region}"
                 )
                 print(f"Running update: {update_addon_cmd}")
                 subprocess.run(update_addon_cmd, shell=True, check=True)
                 print("Addon update initiated.")
            else:
                 print("Addon already configured with the correct role ARN.")


        except subprocess.CalledProcessError as e:
            # Check stderr for the specific exception type
            stderr_output = e.stderr.lower()
            if "resourcenotfoundexception" in stderr_output:
                print(f"Addon '{addon_name}' not found. Creating addon...")
                # Using --resolve-conflicts OVERWRITE for creation as well
                create_addon_cmd = (
                    f"aws eks create-addon --cluster-name {cluster_name} --addon-name {addon_name} "
                    f"--service-account-role-arn {role_arn} --resolve-conflicts OVERWRITE --region {region}"
                )
                print(f"Running create: {create_addon_cmd}")
                subprocess.run(create_addon_cmd, shell=True, check=True)
                print("Addon creation initiated.")
            else:
                print(f"Error describing addon: {e}")
                print(f"Stderr: {e.stderr}")
                return False

        # 5. Wait for Addon to become active
        print("Waiting for addon to become active (up to 5 minutes)...")
        max_wait_time = 300  # seconds
        start_time = time.time()
        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > max_wait_time:
                 print("Error: Timeout waiting for addon to become active.")
                 return False

            try:
                result = subprocess.run(describe_addon_cmd, shell=True, check=True, capture_output=True, text=True)
                addon_status = json.loads(result.stdout)['addon']['status']
                print(f"Current addon status: {addon_status} (Elapsed: {int(elapsed_time)}s)")
                if addon_status == "ACTIVE":
                    print(f"Addon '{addon_name}' is active.")
                    break
                elif addon_status in ["CREATE_FAILED", "DEGRADED", "DELETE_FAILED", "UPDATE_FAILED"]:
                    print(f"Error: Addon entered failed/degraded state: {addon_status}")
                    # Fetch and print addon health issues
                    try:
                         issues_cmd = f"aws eks describe-addon --cluster-name {cluster_name} --addon-name {addon_name} --query addon.health.issues --region {region}"
                         issues_result = subprocess.run(issues_cmd, shell=True, check=True, capture_output=True, text=True)
                         print(f"Addon Health Issues: {issues_result.stdout.strip()}")
                    except Exception as issue_err:
                         print(f"Could not fetch addon health issues: {issue_err}")
                    return False
                time.sleep(15) # Wait before checking again
            except subprocess.CalledProcessError as e:
                 print(f"Error checking addon status: {e}")
                 print(f"Stderr: {e.stderr}")
                 # Don't immediately fail, maybe transient issue
                 time.sleep(15)
            except Exception as e_wait:
                 print(f"Unexpected error waiting for addon: {str(e_wait)}")
                 return False

        # 6. Verify EBS CSI Controller deployment exists and is ready via kubectl
        print("Verifying EBS CSI controller deployment status via kubectl...")
        controller_deployment = "ebs-csi-controller"
        controller_namespace = "kube-system"

        # First, check if the deployment exists
        check_deploy_cmd = f"kubectl get deployment {controller_deployment} -n {controller_namespace} --ignore-not-found"
        try:
            result = subprocess.run(check_deploy_cmd, shell=True, check=True, capture_output=True, text=True)
            if not result.stdout: # If stdout is empty, deployment not found
                 print(f"Error: Deployment '{controller_deployment}' not found in namespace '{controller_namespace}' even though addon status might be ACTIVE.")
                 print("This indicates a problem with the addon installation within the cluster.")
                 print("Please check EKS control plane logs or addon health status in the AWS console/CLI.")
                 return False
            print(f"Deployment '{controller_deployment}' found in namespace '{controller_namespace}'.")
        except subprocess.CalledProcessError as get_err:
             # Should not happen with --ignore-not-found unless kubectl fails entirely
             print(f"Error checking for deployment '{controller_deployment}': {get_err}")
             print(f"Stderr: {get_err.stderr}")
             return False
        except FileNotFoundError:
             print("Error: 'kubectl' command not found. Please ensure kubectl is installed and in your PATH.")
             return False

        # If deployment exists, wait for it to be ready
        print(f"Waiting for deployment '{controller_deployment}' rollout to complete (up to 5m)...")
        wait_cmd = f"kubectl rollout status deployment/{controller_deployment} -n {controller_namespace} --timeout=5m"
        try:
            # Use capture_output=True to see the rollout status messages
            rollout_result = subprocess.run(wait_cmd, shell=True, check=True, capture_output=True, text=True)
            print(rollout_result.stdout) # Print successful rollout message
            print(f"Deployment '{controller_deployment}' in namespace '{controller_namespace}' is ready.")
        except subprocess.CalledProcessError as roll_err:
            print(f"Error waiting for deployment '{controller_deployment}': {roll_err}")
            print(f"Stdout: {roll_err.stdout}")
            print(f"Stderr: {roll_err.stderr}")
            # Attempt to get pod logs for debugging
            try:
                pods_cmd = f"kubectl get pods -n {controller_namespace} -l app=ebs-csi-controller --no-headers -o custom-columns=\":metadata.name\""
                pods_result = subprocess.run(pods_cmd, shell=True, check=True, capture_output=True, text=True)
                pod_names = pods_result.stdout.strip().split('\n')
                if pod_names and pod_names[0]:
                    log_cmd = f"kubectl logs {pod_names[0]} -n {controller_namespace}"
                    print(f"\nAttempting to fetch logs from pod {pod_names[0]}:")
                    log_result = subprocess.run(log_cmd, shell=True, check=False, capture_output=True, text=True) # Don't check=True, might fail
                    print("--- Pod Logs Start ---")
                    print(log_result.stdout)
                    print(log_result.stderr)
                    print("--- Pod Logs End ---")
            except Exception as log_e:
                print(f"Could not fetch controller pod logs: {log_e}")
            print("Please check the status of the EBS CSI pods in kube-system namespace manually.")
            return False
        except FileNotFoundError:
             print("Error: 'kubectl' command not found. Please ensure kubectl is installed and in your PATH.")
             return False

        # Note: StorageClass creation moved to main function

        print("EBS CSI Driver setup via EKS Addon completed successfully and controller is ready.")
        return True

    except subprocess.CalledProcessError as e:
        print(f"An AWS CLI or kubectl command failed: {e}")
        print(f"Command: {' '.join(e.cmd) if isinstance(e.cmd, list) else e.cmd}") # Handle list vs string cmd
        print(f"Return Code: {e.returncode}")
        # Decode stderr if it's bytes
        stderr_output = e.stderr
        if isinstance(stderr_output, bytes):
            try:
                stderr_output = stderr_output.decode('utf-8', errors='replace')
            except Exception:
                 stderr_output = str(stderr_output) # Fallback
        print(f"Stderr: {stderr_output}")
        return False
    except Exception as e:
        import traceback
        print(f"An unexpected error occurred in ensure_ebs_csi_driver: {str(e)}")
        print(traceback.format_exc()) # Print full traceback for debugging
        return False

# Function to create the EBS Storage Class
def create_ebs_storage_class():
    print("\n=== Creating EBS Storage Class 'ebs-sc' ===")
    storage_class_yaml = """
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-sc
# Removed default class annotation to avoid conflicts
#  annotations:
#    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
volumeBindingMode: Immediate # Use Immediate binding
parameters:
  type: gp2 # Specify gp2 volume type
  encrypted: "true" # Enable encryption
"""
    try:
        print("Applying StorageClass using kubectl...")
        # Ensure kubectl is configured for the correct cluster (update_kubeconfig should handle this)
        apply_sc_cmd = ["kubectl", "apply", "-f", "-"]
        process = subprocess.run(apply_sc_cmd, input=storage_class_yaml, text=True, check=True, capture_output=True)
        print(f"kubectl apply stdout: {process.stdout}")
        # print(f"kubectl apply stderr: {process.stderr}") # Usually empty on success
        print("StorageClass 'ebs-sc' created or configured successfully.")
        return True
    except subprocess.CalledProcessError as sc_err:
        print(f"Error applying storage class via kubectl: {sc_err}")
        print(f"Stderr: {sc_err.stderr}")
        # Check if it already exists, which isn't necessarily an error
        if "already exists" in sc_err.stderr.lower():
             print("StorageClass 'ebs-sc' likely already exists. Continuing...")
             return True # Treat as success if it already exists
        else:
             return False
    except FileNotFoundError:
        print("Error: 'kubectl' command not found. Please ensure kubectl is installed and in your PATH.")
        return False
    except Exception as e:
         print(f"An unexpected error occurred during StorageClass creation: {e}")
         return False


# Function to deploy Solace broker
def deploy_solace(ha_mode, use_ecr=False, cluster_name=None):
    print("\n=== Deploying Solace PubSub+ Broker ===")
    
    # Cluster name is expected to be passed correctly now
    # if not cluster_name:
    #     cluster_name = input("Enter the name of your EKS cluster: ").strip()
    
    # Prerequisites (EBS Driver, Storage Class) should be handled in main before calling this

    # Remove existing repository if it exists to avoid conflicts
    try:
        subprocess.run("helm repo remove solacecharts", shell=True, check=False)
    except:
        pass
    
    # Add the Solace Helm chart repository
    subprocess.run(
        "helm repo add solacecharts https://solaceproducts.github.io/pubsubplus-kubernetes-helm-quickstart/helm-charts",
        shell=True, check=True
    )
    subprocess.run("helm repo update", shell=True, check=True)
    
    # Prepare base Helm command
    helm_cmd = "helm install solace solacecharts/pubsubplus"
    
    # Configure redundancy based on HA mode and set admin password
    # Also configure storage to use EBS storage class
    print("Using the ebs-sc storage class for persistent volumes")
    
    if ha_mode == "n":
        print("Deploying Solace in Standalone mode...")
        helm_cmd += " --set solace.redundancy=false,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc"
    else:
        print("Deploying Solace in HA mode...")
        helm_cmd += " --set solace.redundancy=true,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc"
    
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
            # Replace the existing --set with our new combined one using the correct parameter name image.pullSecretName
            if ha_mode == "n":
                helm_cmd = helm_cmd.replace(" --set solace.redundancy=false,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc",
                                         f" --set solace.redundancy=false,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc,image.repository={registry_url}/{image_name},image.tag={image_tag},image.pullSecretName=ecr-secret")
            else:
                helm_cmd = helm_cmd.replace(" --set solace.redundancy=true,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc",
                                         f" --set solace.redundancy=true,solace.usernameAdminPassword=admin,storage.persistent=true,storage.useStorageClass=ebs-sc,image.repository={registry_url}/{image_name},image.tag={image_tag},image.pullSecretName=ecr-secret")
            
            print(f"Using image: {registry_url}/{image_name}:{image_tag} with pull secret: ecr-secret")
            
            # Add namespace to helm command if not default
            if namespace != "default":
                helm_cmd += f" --namespace {namespace} --create-namespace"
    
    # Execute the Helm command
    print(f"Running: {helm_cmd}")
    subprocess.run(helm_cmd, shell=True, check=True)
    
    print("\nSolace broker deployment initiated!")
    print("You can check the status with: kubectl get pods")

# Validate input
def validate_name(name, resource_type):
    if not name:
        return False
    # AWS resource naming rules: letters, numbers, hyphens
    pattern = re.compile(r'^[a-zA-Z][-a-zA-Z0-9]{0,98}[a-zA-Z0-9]$')
    if not pattern.match(name):
        print(f"Error: {resource_type} name must start with a letter, contain only letters, numbers, and hyphens, and be between 2-100 characters.")
        return False
    return True

# Validate numeric input
def validate_number(value, min_val, max_val, name):
    try:
        num = int(value)
        if num < min_val or num > max_val:
            print(f"Error: {name} must be between {min_val} and {max_val}.")
            return False
        return True
    except ValueError:
        print(f"Error: {name} must be a number.")
        return False

# Get user input for cluster configuration
def get_user_input():
    print("\n=== EKS Cluster Configuration ===")
    
    # Cluster name
    while True:
        cluster_name = input(f"Enter EKS cluster name (default: {DEFAULT_CLUSTER_NAME}): ").strip()
        if not cluster_name:
            cluster_name = DEFAULT_CLUSTER_NAME
            print(f"Using default cluster name: {cluster_name}")
            break
        if validate_name(cluster_name, "Cluster"):
            break
    
    # Nodegroup name
    while True:
        nodegroup_name = input(f"Enter nodegroup name (default: {DEFAULT_NODEGROUP_NAME}): ").strip()
        if not nodegroup_name:
            nodegroup_name = DEFAULT_NODEGROUP_NAME
            print(f"Using default nodegroup name: {nodegroup_name}")
            break
        if validate_name(nodegroup_name, "Nodegroup"):
            break
    
    # Instance type
    instance_type = input(f"Enter instance type for nodes (default: {DEFAULT_INSTANCE_TYPE}): ").strip()
    if not instance_type:
        instance_type = DEFAULT_INSTANCE_TYPE
        print(f"Using default instance type: {instance_type}")
    
    # Node count
    while True:
        min_nodes_input = input(f"Enter minimum number of nodes (default: {DEFAULT_MIN_NODES}): ").strip()
        if not min_nodes_input:
            min_nodes = DEFAULT_MIN_NODES
            print(f"Using default minimum nodes: {min_nodes}")
            break
        if validate_number(min_nodes_input, 1, 20, "Minimum nodes"):
            min_nodes = int(min_nodes_input)
            break
    
    while True:
        max_nodes_input = input(f"Enter maximum number of nodes (default: {DEFAULT_MAX_NODES}): ").strip()
        if not max_nodes_input:
            max_nodes = DEFAULT_MAX_NODES
            print(f"Using default maximum nodes: {max_nodes}")
        else:
            if validate_number(max_nodes_input, min_nodes, 20, "Maximum nodes"):
                max_nodes = int(max_nodes_input)
            else:
                continue
        break
    
    while True:
        desired_nodes_input = input(f"Enter desired number of nodes (default: {DEFAULT_DESIRED_NODES}): ").strip()
        if not desired_nodes_input:
            desired_nodes = DEFAULT_DESIRED_NODES
            print(f"Using default desired nodes: {desired_nodes}")
        else:
            if validate_number(desired_nodes_input, min_nodes, max_nodes, "Desired nodes"):
                desired_nodes = int(desired_nodes_input)
            else:
                continue
        break
    
    return {
        'cluster_name': cluster_name,
        'nodegroup_name': nodegroup_name,
        'instance_type': instance_type,
        'min_nodes': min_nodes,
        'max_nodes': max_nodes,
        'desired_nodes': desired_nodes
    }

# Main function to drive the script
def main():
    try:
        # Get user input for cluster configuration
        config = get_user_input()
        
        print("\n=== Starting EKS Cluster Creation ===")
        
        # Step 1: Create VPC
        vpc_id = create_vpc()

        # Step 2: Create Subnets in two AZs
        subnet_ids = create_subnets(vpc_id)

        # Step 3: Create Route Table and associate with Subnets
        create_route_table(vpc_id, subnet_ids)

        # Step 4: Create IAM roles (if not exists)
        cluster_role_arn, node_role_arn = create_iam_roles()

        # Step 5: Create EKS Cluster
        create_cluster(subnet_ids, cluster_role_arn, config['cluster_name'])

        # Step 6: Create Node Group
        create_nodegroup(
            subnet_ids,
            node_role_arn,
            config['cluster_name'],
            config['nodegroup_name'],
            config['instance_type'],
            config['min_nodes'],
            config['max_nodes'],
            config['desired_nodes']
        )

        # Step 7: Update kubectl configuration to access the cluster
        update_kubeconfig(config['cluster_name'])

        # Step 8: Ensure EBS CSI Driver Addon is installed and ready (includes kubectl check now)
        if not ensure_ebs_csi_driver(config['cluster_name']):
             print("\nError: EBS CSI Driver setup failed. Aborting Solace deployment.")
             sys.exit(1) # Exit if driver setup fails

        # Step 9: Create the EBS Storage Class (AFTER driver is confirmed ready)
        if not create_ebs_storage_class():
             print("\nError: Failed to create EBS Storage Class 'ebs-sc'. Aborting Solace deployment.")
             sys.exit(1) # Exit if SC creation fails

        print("\n=== EKS Cluster and Prerequisites Ready ===")
        print(f"Cluster Name: {config['cluster_name']}")
        print(f"Nodegroup: {config['nodegroup_name']}")
        print(f"Instance Type: {config['instance_type']}")
        print(f"Nodes: {config['desired_nodes']} (min: {config['min_nodes']}, max: {config['max_nodes']})")
        print("\nYou can now use kubectl to interact with your cluster.")
        
        # Ask if user wants to deploy Solace
        deploy_solace_input = input("\nDo you want to deploy Solace PubSub+ to this cluster? (y/n): ").lower().strip()
        if deploy_solace_input == 'y':
            # Ask for HA mode
            while True:
                ha_mode = input("Do you want HA mode for Solace? (y/n): ").lower().strip()
                if ha_mode in ["y", "n"]:
                    break
                print("Please enter 'y' or 'n'")
            
            # Ask for ECR image
            use_ecr = input("Do you want to use a Solace image from AWS ECR? (y/n): ").lower().strip() == 'y'
            
            # Deploy Solace with the cluster name
            deploy_solace(ha_mode, use_ecr, config['cluster_name'])
            
            print("\nSolace deployment complete! You can check the status with: kubectl get pods")
        
    except ClientError as e:
        print(f"\nError: AWS API Error: {e}")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
