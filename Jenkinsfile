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
                echo '?îç [ÏΩîÎìú ?àÏßà] SonarQube ?ïÏ†Å ÏΩîÎìú Î∂ÑÏÑù ?òÌñâ...'
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
curl -sLO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
                        chmod +x ./kubectl-argo-rollouts-linux-amd64
                        ./kubectl-argo-rollouts-linux-amd64 -n $K8S_NAMESPACE status ai-service --timeout=300s
                    '''
                }
            }
        }

        stage('LLM Judge') {
            steps {
                echo '?§ñ [LLM Judge] Ï∂îÏ≤ú ?àÏßà ?âÍ? Ï§?..'
                withCredentials([[
                    $class: 'AmazonWebServicesCredentialsBinding',
                    credentialsId: "${AWS_CRED_ID}",
                    accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                    secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                ]]) {
                sh '''
                    aws eks update-kubeconfig --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME"
curl -sLO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
                    chmod +x ./kubectl-argo-rollouts-linux-amd64
                    ./kubectl-argo-rollouts-linux-amd64 -n moneylog status ai-service --timeout=360s
                    
                    AI_POD=$(kubectl get pod -n moneylog -l app=ai-service --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
                    echo "?¨Ïö©??Pod: $AI_POD"
                    
                    for i in $(seq 1 24); do
                        STATUS=$(kubectl exec -n moneylog $AI_POD -- wget -qO- http://localhost:8000/health 2>/dev/null || echo "")
                        if [ -n "$STATUS" ]; then
                            echo "?úÎ≤Ñ Ï§ÄÎπ??ÑÎ£å: $STATUS"
                            break
                        fi
                        echo "?úÎ≤Ñ ?ÄÍ∏?Ï§?.. ($i/24)"
                        sleep 5
                    done
                    
                    AI_POD=$(kubectl get pod -n moneylog -l app=ai-service --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
                    kubectl cp llm_benchmark.py $AI_POD:/tmp/llm_benchmark.py --namespace moneylog
                    kubectl exec -n moneylog $AI_POD -- \
                        sh -c 'EVAL_BASE_URL=http://localhost:8000 EVAL_WAIT_SEC=60 EVAL_CALL_INTERVAL=25 python3 /tmp/llm_benchmark.py'
                '''
                }
            }
            post {
                failure {
                    echo '??LLM Judge ?§Ìå® - ?¥Ï†Ñ Î≤ÑÏ†Ñ?ºÎ°ú Î°§Î∞±?©Îãà??..'
                    withCredentials([[
                        $class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: "${AWS_CRED_ID}",
                        accessKeyVariable: 'AWS_ACCESS_KEY_ID',
                        secretKeyVariable: 'AWS_SECRET_ACCESS_KEY'
                    ]]) {
                        sh '''
                            aws eks update-kubeconfig --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME"
                            kubectl rollout undo -n moneylog rollout/ai-service
                            kubectl rollout status -n moneylog rollout/ai-service --timeout=300s
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            echo 'Cleaning local Docker image cache...'
            sh "docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} || true"
            sh "docker builder prune -af || true"
            sh "docker system prune -af --volumes || true"
        }
        success {
            echo 'EKS deployment succeeded.'
            sh """
            curl -H "Content-Type: application/json" \\
                 -d '{"content": "??**Î∞∞Ìè¨ ?±Í≥µ**: ${env.JOB_NAME} [ÎπåÎìú #${env.BUILD_NUMBER}] Î∞∞Ìè¨Í∞Ä Ïπ¥ÎÇòÎ¶?Canary) Î∞©Ïãù?ºÎ°ú ?àÏ†Ñ?òÍ≤å ?ÑÎ£å?òÏóà?µÎãà?? ??"}' \\
                 ""
            """
        }
        failure {
            echo 'Deployment failed. Check the pipeline logs.'
            sh """
            curl -H "Content-Type: application/json" \\
                 -d '{"content": "?ö® **Î∞∞Ìè¨ ?§Ìå®**: ${env.JOB_NAME} [ÎπåÎìú #${env.BUILD_NUMBER}] ?êÎü¨ Î∞úÏÉù! ?åÏù¥?ÑÎùº??Î°úÍ∑∏Î•??ïÏù∏?¥Ï£º?∏Ïöî."}' \\
                 ""
            """
        }
    }
}