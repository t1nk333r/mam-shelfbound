// Jenkins CI/CD for the multibranch job discovered under the d7eeem organization
// folder. This pipeline owns publishing: it tests, builds, pushes the container
// image to GHCR, and cuts the release tag. The GitHub Actions workflow is
// limited to running the test suite.
// Resolves a credential that may be stored either as Username/password or as
// Secret text, binds it to CRED_USER/CRED_TOKEN, and runs the body. Probing up
// front (rather than wrapping the body in try/catch) keeps a genuine build
// failure from being mistaken for a binding mismatch.
def withPat(String credentialsId, Closure body) {
  boolean userPass = false
  try {
    withCredentials([usernamePassword(
      credentialsId: credentialsId,
      usernameVariable: 'PROBE_USER',
      passwordVariable: 'PROBE_TOKEN'
    )]) {
      userPass = true
    }
  } catch (ignored) {
    userPass = false
  }

  if (userPass) {
    withCredentials([usernamePassword(
      credentialsId: credentialsId,
      usernameVariable: 'CRED_USER',
      passwordVariable: 'CRED_TOKEN'
    )]) {
      body()
    }
  } else {
    // ghcr.io and github.com both authenticate on the token alone; the
    // username only has to be non-empty.
    withCredentials([string(credentialsId: credentialsId, variable: 'CRED_TOKEN')]) {
      withEnv(['CRED_USER=x-access-token']) {
        body()
      }
    }
  }
}

pipeline {
  agent { label 'docker' }

  environment {
    REGISTRY = 'ghcr.io'
    // Published image path. Kept separate from the git remote on purpose: the
    // repository lives under a personal account, images stay on the documented
    // ghcr.io/d7eeem path that README.md and existing deployments point at.
    IMAGE_REPO = 'ghcr.io/d7eeem/mam-shelfbound'
    // PAT with write:packages, used for the registry push.
    GHCR_CREDENTIALS_ID = 'ghcr-pat'
    // PAT with repo scope, used to push the release tag and create the
    // GitHub release. May be the same credential as GHCR_CREDENTIALS_ID.
    GITHUB_CREDENTIALS_ID = 'github-release-token'
    // Set to 'linux/amd64' alone if the agent cannot emulate arm64.
    PLATFORMS = 'linux/amd64,linux/arm64'
    BUILDX_BUILDER = 'mam-shelfbound-ci'
    DEFAULT_BRANCH = 'master'
  }

  options {
    timestamps()
    disableConcurrentBuilds(abortPrevious: true)
    timeout(time: 60, unit: 'MINUTES')
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

    stage('Preflight') {
      steps {
        sh '''
          set -euo pipefail

          # Work out what this agent can actually build, and record it for the
          # build stages. Anything unavailable degrades the build rather than
          # failing it, so a missing buildx plugin or a docker daemon that will
          # not run privileged containers still produces a published image.
          builder=""
          platforms="linux/amd64"

          if docker buildx version >/dev/null 2>&1; then
            # The default "docker" driver cannot build multi-platform images.
            if ! docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
              docker buildx create --name "$BUILDX_BUILDER" --driver docker-container --bootstrap || true
            fi

            if docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
              builder="$BUILDX_BUILDER"
            else
              echo "WARNING: could not create a docker-container builder; using the default builder." >&2
            fi

            supported="$(docker buildx inspect --bootstrap ${builder:+"$builder"} 2>/dev/null | grep -i '^Platforms:' || true)"
            case "$PLATFORMS" in
              *arm64*)
                case "$supported" in
                  *linux/arm64*) ;;
                  *)
                    # Register the qemu handlers, then look again.
                    docker run --privileged --rm tonistiigi/binfmt --install arm64 >/dev/null 2>&1 || true
                    supported="$(docker buildx inspect --bootstrap ${builder:+"$builder"} 2>/dev/null | grep -i '^Platforms:' || true)"
                    ;;
                esac
                case "$supported" in
                  *linux/arm64*) platforms="$PLATFORMS" ;;
                  *)
                    echo "WARNING: this agent cannot build linux/arm64 (no qemu/binfmt handlers)." >&2
                    echo "WARNING: publishing linux/amd64 only. The build is marked unstable." >&2
                    ;;
                esac
                ;;
              *)
                platforms="$PLATFORMS"
                ;;
            esac
          else
            echo "WARNING: docker buildx is not installed; publishing linux/amd64 only." >&2
          fi

          {
            echo "BUILDER=$builder"
            echo "BUILD_PLATFORMS=$platforms"
          } > buildx.env

          echo "Builder: ${builder:-<default>}"
          echo "Platforms: $platforms"
        '''
        script {
          def requested = env.PLATFORMS
          def effective = readFile('buildx.env')
            .split('\n')
            .find { it.startsWith('BUILD_PLATFORMS=') }
            ?.substring('BUILD_PLATFORMS='.length())
            ?.trim()
          env.BUILD_PLATFORMS = effective
          if (effective != requested) {
            // Visible in the build history rather than buried in the log: a
            // published image missing an architecture is easy to miss.
            unstable("Building ${effective} instead of ${requested}")
          }
        }
      }
    }

    stage('Determine version') {
      steps {
        sh '''
          set -euo pipefail

          # Multibranch checkouts do not always bring tags along, and the whole
          # version scheme is derived from them.
          git fetch --tags --force --quiet origin

          short_sha="$(git rev-parse --short=7 HEAD)"
          branch="${BRANCH_NAME:-${GIT_BRANCH:-unknown}}"
          is_release=false
          create_tag=false
          major_minor="0.0"

          if [ -n "${CHANGE_ID:-}" ]; then
            # Pull request build: never publish.
            publish=false
          else
            publish=true
          fi

          if [ "$publish" = "true" ] && [ "$branch" = "$DEFAULT_BRANCH" ]; then
            # Every build of the default branch cuts a new patch release, even
            # when HEAD already carries a release tag from an earlier build.
            latest_tag="$(
              git tag --list 'v[0-9]*.[0-9]*.[0-9]*' \
                | grep -E '^v[0-9]+\\.[0-9]+\\.[0-9]+$' \
                | sort -V \
                | tail -n 1 || true
            )"
            latest_version="${latest_tag#v}"
            if [ -z "$latest_version" ]; then
              latest_version="0.0.0"
            fi

            IFS=. read -r major minor patch <<EOF
$latest_version
EOF

            # Skip over any version whose tag already exists, so a re-run never
            # collides with a tag the previous run pushed.
            while :; do
              patch=$((patch + 1))
              version="${major}.${minor}.${patch}"
              tag="v${version}"
              if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
                break
              fi
            done

            create_tag=true
            major_minor="${major}.${minor}"
            is_release=true
          else
            safe_ref="$(
              printf '%s' "$branch" \
                | tr '[:upper:]/' '[:lower:]-' \
                | tr -cd 'a-z0-9_.-'
            )"
            if [ -z "$safe_ref" ]; then
              safe_ref="manual"
            fi
            version="snapshot-${safe_ref}-${short_sha}"
            tag="$version"
          fi

          {
            echo "version=$version"
            echo "tag=$tag"
            echo "publish=$publish"
            echo "create_tag=$create_tag"
          } > version.env

          # One image reference per line, consumed by the build stage.
          : > docker-tags.txt
          echo "${IMAGE_REPO}:sha-${short_sha}" >> docker-tags.txt
          if [ "$is_release" = "true" ]; then
            echo "${IMAGE_REPO}:${tag}" >> docker-tags.txt
            echo "${IMAGE_REPO}:${version}" >> docker-tags.txt
            echo "${IMAGE_REPO}:${major_minor}" >> docker-tags.txt
            echo "${IMAGE_REPO}:latest" >> docker-tags.txt
          else
            echo "${IMAGE_REPO}:${version}" >> docker-tags.txt
          fi

          echo "Version: $version"
          echo "Image tags:"
          cat docker-tags.txt
        '''
        script {
          readFile('version.env').split('\n').each { line ->
            def entry = line.trim()
            if (entry) {
              def split = entry.indexOf('=')
              env[entry.substring(0, split)] = entry.substring(split + 1)
            }
          }
        }
      }
    }

    stage('Build and smoke test') {
      steps {
        sh '''
          set -euo pipefail
          IMAGE="mam-shelfbound:ci-${BUILD_NUMBER}"

          # Single-platform --load build so the image is runnable locally; the
          # multi-platform push below reuses this layer cache.
          . ./buildx.env

          docker buildx build \
            ${BUILDER:+--builder "$BUILDER"} \
            --platform linux/amd64 \
            --build-arg APP_VERSION="$version" \
            -t "$IMAGE" \
            --load \
            .

          docker run --rm \
            -e MAM_COOKIE=ci-cookie \
            -e HISTORY_DB_URL=sqlite:////tmp/history.db \
            "$IMAGE" python -m py_compile main.py
        '''
      }
    }

    stage('Push image') {
      when {
        expression { env.publish == 'true' }
      }
      steps {
        script {
          withPat(env.GHCR_CREDENTIALS_ID) {
            sh '''
              set -euo pipefail

              echo "$CRED_TOKEN" | docker login "$REGISTRY" -u "$CRED_USER" --password-stdin

              tag_args=""
              while IFS= read -r ref; do
                [ -n "$ref" ] || continue
                tag_args="$tag_args -t $ref"
              done < docker-tags.txt

              . ./buildx.env

              docker buildx build \
                ${BUILDER:+--builder "$BUILDER"} \
                --platform "$BUILD_PLATFORMS" \
                --build-arg APP_VERSION="$version" \
                --label "org.opencontainers.image.version=$version" \
                --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
                --label "org.opencontainers.image.source=https://github.com/$(git remote get-url origin | sed -E 's#.*github\\.com[:/]##; s#\\.git$##')" \
                --cache-from "type=registry,ref=${IMAGE_REPO}:buildcache" \
                --cache-to "type=registry,ref=${IMAGE_REPO}:buildcache,mode=max" \
                $tag_args \
                --push \
                .
            '''
          }
        }
      }
    }

    stage('Release') {
      when {
        expression { env.create_tag == 'true' }
      }
      steps {
        script {
          withPat(env.GITHUB_CREDENTIALS_ID) {
            sh '''
              set -euo pipefail

              slug="$(git remote get-url origin | sed -E 's#.*github\\.com[:/]##; s#\\.git$##')"

              git -c user.name="jenkins" -c user.email="jenkins@localhost" tag "$tag"
              git push "https://${CRED_USER}:${CRED_TOKEN}@github.com/${slug}.git" "refs/tags/${tag}"

              notes="Published container image:"
              while IFS= read -r ref; do
                [ -n "$ref" ] || continue
                notes="${notes}
- \\`${ref}\\`"
              done < docker-tags.txt

              body="$(
                printf '%s' "$notes" \
                  | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
              )"

              curl --fail --silent --show-error \
                -X POST \
                -H "Authorization: Bearer ${CRED_TOKEN}" \
                -H "Accept: application/vnd.github+json" \
                "https://api.github.com/repos/${slug}/releases" \
                -d "{\\"tag_name\\":\\"${tag}\\",\\"name\\":\\"${tag}\\",\\"generate_release_notes\\":true,\\"body\\":${body}}" \
                > /dev/null

              echo "Released ${tag}"
            '''
          }
        }
      }
    }
  }

  post {
    always {
      sh '''
        docker image rm -f "mam-shelfbound:ci-${BUILD_NUMBER}" || true
        docker logout "$REGISTRY" || true
      '''
    }
  }
}
