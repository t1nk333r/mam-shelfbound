// Jenkins CI for the multibranch job discovered under the d7eeem organization
// folder. Publishing remains in the existing GitHub Actions workflow; this
// pipeline is intentionally limited to test and Docker-build verification.
pipeline {
  agent { label 'docker' }

  options {
    timestamps()
    disableConcurrentBuilds(abortPrevious: true)
    timeout(time: 30, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  stages {
    stage('Tests (Python 3.12)') {
      steps {
        sh '''
          set -euo pipefail
          export UV_CACHE_DIR="$WORKSPACE/.uv-cache"
          export UV_PYTHON_INSTALL_DIR="$WORKSPACE/.uv-python"
          uv venv --clear --python 3.12 .venv
          . .venv/bin/activate
          uv pip install -r requirements.txt -r requirements-dev.txt
          python -m py_compile app/main.py
          cd app
          python -m pytest -q
        '''
      }
    }

    stage('Build container image') {
      steps {
        sh '''
          set -euo pipefail
          IMAGE="mam-shelfbound:ci-${BUILD_NUMBER}"
          docker build --build-arg APP_VERSION="ci-${BUILD_NUMBER}" -t "$IMAGE" .
          docker run --rm \
            -e MAM_COOKIE=ci-cookie \
            -e HISTORY_DB_URL=sqlite:////tmp/history.db \
            "$IMAGE" python -m py_compile main.py
        '''
      }
    }
  }

  post {
    always {
      sh 'docker image rm -f "mam-shelfbound:ci-${BUILD_NUMBER}" || true'
    }
  }
}
