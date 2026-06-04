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

    stage('SonarQube Analysis') {
        steps {
            echo '🔍 [코드 품질] SonarQube 정적 코드 분석 수행...'
            catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE') {
                withSonarQubeEnv('SonarQube-Server') {
                    script {
                        def scannerHome = tool 'py-sonar'
                        sh "${scannerHome}/bin/sonar-scanner"
                    }
                }
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }
        }
    }

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
                """
            }
        }

        stage('Deploy to AWS EKS') {
            steps {
                echo 'Deploying to EKS...'
                withCredentials([
                    [
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: "${AWS_CRED_ID}",
                        accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                        secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                    ],
                    string(credentialsId: env.GATEWAY_TOKEN, variable: 'GATEWAY_SECRET_TOKEN')
                ]) {
                    sh '''
                        export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
                        export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
                        export AWS_DEFAULT_REGION=$AWS_REGION

                        aws eks update-kubeconfig --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME"

                        kubectl create secret generic ai-service-secret \
                        --namespace=$K8S_NAMESPACE \
                        --from-literal=GATEWAY_SECRET_TOKEN=$GATEWAY_SECRET_TOKEN \
                        --dry-run=client -o yaml | kubectl apply -f -

                        sed -i "s|IMAGE_TAG_PLACEHOLDER|$IMAGE_TAG|g" k8s/deployment.yaml

                        kubectl create namespace "$K8S_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - --validate=false
                        kubectl apply -f k8s/ --validate=false
                        kubectl -n "$K8S_NAMESPACE" rollout status deployment/ai-service --timeout=180s
                    '''
                }
            }
        }
    }

    post {
        always {
            echo 'Cleaning local Docker image cache...'
            sh "docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} || true"
        }
        success {
            echo 'EKS deployment succeeded.'
        }
        failure {
            echo 'Deployment failed. Check the pipeline logs.'
        }
    }
}