from tameru.compress_context import compress_context


def test_kubectl_describe_job_keeps_failure_and_backoff():
    text = """\
Name: nightly-report
Namespace: batch
Selector: batch.kubernetes.io/job-name=nightly-report
Labels: batch.kubernetes.io/controller-uid=11111111-2222-3333-4444-555555555555
      batch.kubernetes.io/job-name=nightly-report
Annotations: <none>
Parallelism: 1
Completions: 1
Completion Mode: NonIndexed
Backoff Limit: 6
Completed At: <none>
Start Time: Mon, 01 Jan 2024 00:00:00 +0000
Status: Failed
Reason: BackoffLimitExceeded
Message: Job has reached the specified backoff limit
Pods Statuses: 0 Active (0 Ready) / 0 Succeeded / 6 Failed
Pod Template:
  Labels:  batch.kubernetes.io/controller-uid=11111111-2222-3333-4444-555555555555
           batch.kubernetes.io/job-name=nightly-report
  Annotations:  <none>
  Containers:
   report:
    Image: python:3.12
    Port: <none>
    Host Port: <none>
    Command: python /app/nightly_report.py
    Environment:
      REPORT_DATE:  (v1:metadata.creationTimestamp)
      REPORT_REGION:  us-east-1
      REPORT_BUCKET:  s3://nightly-reports
      REPORT_TIMEOUT:  3600
      REPORT_RETRIES:  3
      REPORT_LOG_LEVEL:  INFO
      REPORT_WORKERS:  4
      REPORT_BATCH_SIZE:  1000
      REPORT_ENDPOINT:  https://api.example.com
      REPORT_API_KEY:  (secretKeyRef:nightly-report-api-key)
    Mounts:
      /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-abcde (ro)
  Volumes:
   kube-api-access-abcde:
    Type: Projected (a volume that contains injected data from multiple sources)
Events:
  Type     Reason                Age   From            Message
  ----     ------                ----  ----            -------
  Normal   SuccessfulCreate      10m   job-controller  Created pod: nightly-report-abcde
  Normal   SuccessfulCreate      9m    job-controller  Created pod: nightly-report-bcdef
  Normal   SuccessfulCreate      8m    job-controller  Created pod: nightly-report-cdefg
  Normal   SuccessfulCreate      7m    job-controller  Created pod: nightly-report-defgh
  Normal   SuccessfulCreate      6m    job-controller  Created pod: nightly-report-efghi
  Normal   SuccessfulCreate      5m    job-controller  Created pod: nightly-report-fghij
  Warning  BackoffLimitExceeded  2m    job-controller  Job has reached the specified backoff limit
"""
    result = compress_context(text, "", ccr=False, citations=False)
    compressed_text = result.compressed_text

    assert "6 Failed" in compressed_text
    assert "BackoffLimitExceeded" in compressed_text
    assert len(compressed_text) < len(text)
    assert result.compressed_text != text
