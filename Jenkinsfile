pipeline {
    agent { 
        label 'onprem-agent' 
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
        ansiColor('xterm')
    }

    environment {
        REGISTRY                 = 'registry.gitlab.com'
        IMAGE_NAME               = '5kstration/alarm-service-be'
        IMAGE_TAG                = "${env.BUILD_NUMBER}"
        REGISTRY_CRED_ID         = 'gitlab-registry-credentials'
        GITLAB_CRED_ID           = 'gitlab-git-credentials'
    }

    stages {
        stage('Clone Repository') {
            steps {
                echo '📦 [소스코드] GitLab 리포지토리로부터 최신 소스코드 동기화...'
                checkout scm
            }
        }

        stage('Backend Build & Test') {
            steps {
                echo '☕ [컴파일] jar 패키징 및 테스트 수행...'
                sh './gradlew clean bootJar'
            }
        }

        stage('SonarQube Analysis') {
            steps {
                echo '🔍 [코드 품질] SonarQube 정적 코드 분석 수행...'
                catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE') {
                    withSonarQubeEnv('SonarQube-Server') {
                        sh './gradlew sonar'
                    }
                    timeout(time: 5, unit: 'MINUTES') {
                        waitForQualityGate abortPipeline: true
                    }
                }
            }
        }

        stage('Docker Build & Push to GitLab Registry') {
            steps {
                echo '🐳 [도커 이미지] 빌드 및 GitLab Registry 푸시...'
                withCredentials([usernamePassword(credentialsId: "${REGISTRY_CRED_ID}", usernameVariable: 'REG_USER', passwordVariable: 'REG_PASS')]) {
                    sh """
                        docker build -t ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} .
                        docker tag ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${IMAGE_NAME}:latest
                        docker login -u ${REG_USER} -p ${REG_PASS} ${REGISTRY}
                        docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                        docker push ${REGISTRY}/${IMAGE_NAME}:latest
                    """
                }
            }
        }

        stage('Update Image Tag & Push') {
            steps {
                echo '📝 [Git] deployment.yaml 이미지 태그 업데이트 및 커밋...'
                withCredentials([usernamePassword(credentialsId: "${GITLAB_CRED_ID}", usernameVariable: 'GIT_USER', passwordVariable: 'GIT_TOKEN')]) {
                    sh """
                        sed -i "s|alarm-service-be:.*|alarm-service-be:${IMAGE_TAG}|g" k8s/deployment.yaml
                        git config user.email "jenkins@moneylog.com"
                        git config user.name "Jenkins"
                        git add k8s/deployment.yaml
                        git commit -m "ci: update alarm-service image tag to ${IMAGE_TAG}"
                        git push https://\${GIT_USER}:\${GIT_TOKEN}@gitlab.com/5kstration/alarm-service-BE.git HEAD:main
                    """
                }
            }
        }
    }

    post {
        always {
            echo '🧹 [인프라 정리] 로컬 도커 이미지 캐시 삭제...'
            sh """
                docker rmi ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} || true
                docker rmi ${REGISTRY}/${IMAGE_NAME}:latest || true
            """
        }
        success {
            echo '✅ ArgoCD가 온프렘 k8s 배포를 처리합니다.'
        }
        failure {
            echo '❌ 파이프라인 실패. 로그를 확인하십시오.'
        }
    }
}