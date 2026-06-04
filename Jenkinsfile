pipeline {
    agent {
        label 'onprem-agent'
    }

    options {
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        ansiColor('xterm')
    }

    environment {
        AWS_REGION       = 'ap-northeast-2'
        AWS_ACCOUNT_ID   = '525089404962'
        ECR_REGISTRY     = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
        IMAGE_NAME       = 'ai-service-be'
        IMAGE_TAG        = "${BUILD_NUMBER}"
        EKS_CLUSTER_NAME = 'oka-eks'
        AWS_CRED_ID      = 'aws-iam-jenkins-user-key'
        K8S_NAMESPACE    = 'moneylog'
        GATEWAY_TOKEN    = 'x-gateway-token'
    }

    stages {
        stage('Checkout SCM') {
            steps {
                echo 'Checking out source...'
                checkout scm
            }
        }

        // Python은 별도 빌드 없이 Docker 이미지 빌드 시 pip install 처리
        // Gradle 빌드 스테이지 없음

        stage('AWS ECR Authentication') {
            steps {
                echo 'Logging in to ECR...'
                withCredentials([[
                    $class: 'AmazonWebServicesCredentialsBinding',
                    credentialsId: "${AWS_CRED_ID}",
                    accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                    secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                ]]) {
                    sh '''
                        aws ecr get-login-password --region "$AWS_REGION" | \
                        docker login --username AWS --password-stdin "$ECR_REGISTRY"
                    '''
                }
            }
        }

        stage('Docker Build & Push to ECR') {
            steps {
                echo 'Building and pushing Docker image...'
                sh """
                    docker build -t ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} .
                    docker push ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                    docker tag ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} ${ECR_REGISTRY}/${IMAGE_NAME}:latest
                    docker push ${ECR_REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }
        stage('Update Image Tag & Push') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'gitlab-token',
                    usernameVariable: 'GIT_USER',
                    passwordVariable: 'GIT_TOKEN'
                )]) {
                    sh """
                        sed -i "s|ai-service-be:.*|ai-service-be:${IMAGE_TAG}|g" k8s/deployment.yaml
                        git config user.email "jenkins@moneylog.com"
                        git config user.name "Jenkins"
                        git add k8s/deployment.yaml
                        git commit -m "ci: update ai-service image tag to ${IMAGE_TAG}"
                        git push https://\${GIT_USER}:\${GIT_TOKEN}@gitlab.com/5kstration/ai-service-be.git HEAD:main
                    """
                }
            }
        }
    }

    post {
        always {
            echo 'Cleaning local Docker image cache...'
            sh "docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} || true"
            sh "docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:latest || true"
        }
        success {
            echo 'ArgoCD will handle deployment.'
        }
        failure {
            echo 'Pipeline failed. Check the logs.'
        }
    }
}