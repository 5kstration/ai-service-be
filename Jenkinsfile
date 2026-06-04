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
        AWS_CRED_ID      = 'aws-iam-jenkins-user-key'
        GITLAB_CRED_ID   = 'gitlab-git-credentials'
    }

    stages {
        stage('Checkout SCM') {
            steps {
                echo '📦 [소스코드] GitLab 리포지토리로부터 최신 소스코드 동기화...'
                checkout scm
            }
        }

        stage('Check Commit Author') {
            steps {
                script {
                    def author = sh(script: 'git log -1 --pretty=format:%an', returnStdout: true).trim()
                    if (author == 'Jenkins') {
                        currentBuild.result = 'NOT_BUILT'
                        error('Jenkins 자동 커밋 - 빌드 스킵')
                    }
                }
            }
        }

        stage('AWS ECR Authentication') {
            steps {
                echo '🔐 [ECR] 로그인...'
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
                echo '🐳 [도커 이미지] 빌드 및 ECR 푸시...'
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
                echo '📝 [Git] deployment.yaml 이미지 태그 업데이트 및 커밋...'
                withCredentials([usernamePassword(
                    credentialsId: "${GITLAB_CRED_ID}",
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
            echo '🧹 [인프라 정리] 로컬 도커 이미지 캐시 삭제...'
            sh """
                docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} || true
                docker rmi ${ECR_REGISTRY}/${IMAGE_NAME}:latest || true
            """
        }
        success {
            echo '✅ ArgoCD가 EKS 배포를 처리합니다.'
        }
        failure {
            echo '❌ 파이프라인 실패. 로그를 확인하십시오.'
        }
    }
}