# Integration Examples

This guide shows how to integrate the Whisper API with various automation and workflow tools.

## n8n Integration

### Workflow 1: Transcribe and Process

This workflow triggers when a new audio file is uploaded, transcribes it, and processes the results.

```json
{
  "nodes": [
    {
      "name": "Webhook Trigger",
      "type": "n8n-nodes-base.webhook",
      "parameters": {
        "path": "audio-upload",
        "method": "POST"
      }
    },
    {
      "name": "Start Transcription",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "https://your-whisper-api.run.app/transcribe/start",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {
              "name": "url",
              "value": "={{ $json.audio_url }}"
            },
            {
              "name": "callback_url",
              "value": "={{ $node['Webhook Receive Results'].data.webhook_url }}"
            }
          ]
        }
      }
    },
    {
      "name": "Webhook Receive Results",
      "type": "n8n-nodes-base.webhook",
      "parameters": {
        "path": "transcription-complete",
        "method": "POST"
      }
    },
    {
      "name": "Process Transcription",
      "type": "n8n-nodes-base.function",
      "parameters": {
        "functionCode": "const text = $json.text;\nconst segments = $json.segments;\n\n// Do something with the transcription\nreturn {\n  transcription: text,\n  segment_count: segments.length\n};"
      }
    }
  ]
}
```

### Workflow 2: Poll for Results (Alternative)

If you prefer polling instead of webhooks:

```json
{
  "nodes": [
    {
      "name": "Start Transcription",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "https://your-whisper-api.run.app/transcribe/start",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {
              "name": "url",
              "value": "={{ $json.audio_url }}"
            }
          ]
        }
      }
    },
    {
      "name": "Extract Job ID",
      "type": "n8n-nodes-base.set",
      "parameters": {
        "values": {
          "string": [
            {
              "name": "job_id",
              "value": "={{ $json.job_id }}"
            }
          ]
        }
      }
    },
    {
      "name": "Poll Status",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "GET",
        "url": "=https://your-whisper-api.run.app/transcribe/status/{{ $json.job_id }}",
        "options": {
          "retry": {
            "enabled": true,
            "maxRetries": 10,
            "waitBetweenRetries": 5000
          }
        }
      }
    },
    {
      "name": "Check Status",
      "type": "n8n-nodes-base.if",
      "parameters": {
        "conditions": {
          "string": [
            {
              "value1": "={{ $json.status }}",
              "value2": "done"
            }
          ]
        }
      }
    },
    {
      "name": "Wait and Retry",
      "type": "n8n-nodes-base.wait",
      "parameters": {
        "amount": 5,
        "unit": "seconds"
      }
    }
  ]
}
```

## Python Integration

### Using Callbacks

```python
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Start transcription with callback
def transcribe_audio(audio_url):
    response = requests.post(
        "https://your-whisper-api.run.app/transcribe/start",
        data={
            "url": audio_url,
            "callback_url": "https://your-domain.com/webhook/transcription",
            "diarize": True,
            "language": "en"
        }
    )
    job_data = response.json()
    print(f"Job started: {job_data['job_id']}")
    return job_data

# Webhook endpoint to receive results
@app.route("/webhook/transcription", methods=["POST"])
def handle_transcription():
    data = request.json

    if data["status"] == "done" and data["ok"]:
        print(f"Transcription complete for job {data['job_id']}")
        print(f"Text: {data['text']}")
        print(f"Segments: {len(data['segments'])}")

        # Process the transcription
        process_transcription(data)
    else:
        print(f"Transcription failed: {data.get('error')}")

    return jsonify({"received": True})

def process_transcription(data):
    """Process the transcription results"""
    # Your custom logic here
    pass

if __name__ == "__main__":
    # Example: Start a transcription
    transcribe_audio("https://example.com/meeting.mp3")

    # Start webhook server
    app.run(host="0.0.0.0", port=5000)
```

### Using Polling

```python
import requests
import time

def transcribe_and_wait(audio_url, max_wait=300, poll_interval=5):
    """
    Transcribe audio and wait for results by polling.

    Args:
        audio_url: URL to audio file
        max_wait: Maximum seconds to wait
        poll_interval: Seconds between status checks

    Returns:
        Transcription result dict or None if timeout
    """
    # Start job
    response = requests.post(
        "https://your-whisper-api.run.app/transcribe/start",
        data={
            "url": audio_url,
            "diarize": True,
            "language": "en"
        }
    )

    if response.status_code != 200:
        print(f"Failed to start job: {response.text}")
        return None

    job_data = response.json()
    job_id = job_data["job_id"]
    print(f"Job started: {job_id}")

    # Poll for results
    start_time = time.time()
    while time.time() - start_time < max_wait:
        response = requests.get(
            f"https://your-whisper-api.run.app/transcribe/status/{job_id}"
        )

        if response.status_code != 200:
            print(f"Failed to check status: {response.text}")
            return None

        status_data = response.json()
        status = status_data["status"]

        if status == "done":
            result = status_data["result"]
            if result["ok"]:
                print(f"Transcription complete!")
                return result
            else:
                print(f"Transcription failed: {result}")
                return None

        elif status == "error":
            print(f"Job failed: {status_data.get('result')}")
            return None

        print(f"Status: {status}, waiting...")
        time.sleep(poll_interval)

    print(f"Timeout after {max_wait}s")
    return None

# Example usage
if __name__ == "__main__":
    result = transcribe_and_wait("https://example.com/audio.mp3")

    if result:
        print(f"\nTranscription:\n{result['text']}")
        print(f"\nSegments: {len(result['segments'])}")

        # Print first few segments
        for seg in result['segments'][:3]:
            print(f"  [{seg['start']:.2f}s - {seg['end']:.2f}s] {seg['text']}")
```

## JavaScript/Node.js Integration

### Using Callbacks (Express.js)

```javascript
const express = require('express');
const axios = require('axios');

const app = express();
app.use(express.json());

const WHISPER_API = 'https://your-whisper-api.run.app';

// Start transcription
async function startTranscription(audioUrl, callbackUrl) {
  const response = await axios.post(`${WHISPER_API}/transcribe/start`,
    new URLSearchParams({
      url: audioUrl,
      callback_url: callbackUrl,
      diarize: 'true',
      language: 'en'
    })
  );

  console.log(`Job started: ${response.data.job_id}`);
  return response.data;
}

// Webhook endpoint
app.post('/webhook/transcription', (req, res) => {
  const data = req.body;

  if (data.status === 'done' && data.ok) {
    console.log(`Transcription complete: ${data.job_id}`);
    console.log(`Text: ${data.text}`);

    // Process the transcription
    processTranscription(data);
  } else {
    console.error(`Transcription failed: ${data.error}`);
  }

  res.json({ received: true });
});

function processTranscription(data) {
  // Your custom logic here
}

// Example: Start a job
startTranscription(
  'https://example.com/audio.mp3',
  'https://your-domain.com/webhook/transcription'
);

app.listen(3000, () => {
  console.log('Webhook server listening on port 3000');
});
```

### Using Polling (Async/Await)

```javascript
const axios = require('axios');

const WHISPER_API = 'https://your-whisper-api.run.app';

async function transcribeAndWait(audioUrl, maxWaitSeconds = 300) {
  // Start job
  const startResponse = await axios.post(`${WHISPER_API}/transcribe/start`,
    new URLSearchParams({
      url: audioUrl,
      diarize: 'true'
    })
  );

  const jobId = startResponse.data.job_id;
  console.log(`Job started: ${jobId}`);

  // Poll for results
  const startTime = Date.now();
  const pollInterval = 5000; // 5 seconds

  while ((Date.now() - startTime) / 1000 < maxWaitSeconds) {
    const statusResponse = await axios.get(
      `${WHISPER_API}/transcribe/status/${jobId}`
    );

    const { status, result } = statusResponse.data;

    if (status === 'done') {
      if (result.ok) {
        console.log('Transcription complete!');
        return result;
      } else {
        throw new Error(`Transcription failed: ${JSON.stringify(result)}`);
      }
    } else if (status === 'error') {
      throw new Error(`Job failed: ${JSON.stringify(result)}`);
    }

    console.log(`Status: ${status}, waiting...`);
    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }

  throw new Error(`Timeout after ${maxWaitSeconds}s`);
}

// Example usage
(async () => {
  try {
    const result = await transcribeAndWait('https://example.com/audio.mp3');
    console.log(`\nTranscription:\n${result.text}`);
    console.log(`\nSegments: ${result.segments.length}`);
  } catch (error) {
    console.error('Error:', error.message);
  }
})();
```

## Zapier Integration

While Zapier doesn't natively support this API, you can use Webhooks:

1. **Trigger**: Use "Webhooks by Zapier" → "Catch Hook"
2. **Action 1**: Use "Webhooks by Zapier" → "POST"
   - URL: `https://your-whisper-api.run.app/transcribe/start`
   - Payload Type: `form`
   - Data:
     - `url`: Your audio file URL
     - `callback_url`: The webhook URL from your trigger

3. **Action 2**: Process the transcription results when the callback fires

## Make (Integromat) Integration

Similar to n8n, use HTTP modules:

1. **HTTP - Make a Request**: POST to `/transcribe/start`
2. **Webhook - Custom Webhook**: Receive callback
3. **Router**: Process different status outcomes
4. **Your Action**: Do something with the transcription

## Curl Examples

### Start job and poll

```bash
#!/bin/bash
# Start transcription
RESPONSE=$(curl -s -X POST https://your-whisper-api.run.app/transcribe/start \
  -F "url=https://example.com/audio.mp3" \
  -F "language=en")

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "Job started: $JOB_ID"

# Poll until complete
while true; do
  STATUS=$(curl -s https://your-whisper-api.run.app/transcribe/status/$JOB_ID)
  STATE=$(echo $STATUS | jq -r '.status')

  if [ "$STATE" = "done" ]; then
    echo "Transcription complete!"
    echo $STATUS | jq -r '.result.text'
    break
  elif [ "$STATE" = "error" ]; then
    echo "Transcription failed!"
    echo $STATUS | jq
    break
  fi

  echo "Status: $STATE, waiting..."
  sleep 5
done
```

### With callback

```bash
#!/bin/bash
# Start transcription with callback
curl -X POST https://your-whisper-api.run.app/transcribe/start \
  -F "url=https://example.com/audio.mp3" \
  -F "callback_url=https://webhook.site/your-unique-id" \
  -F "language=en" \
  -F "diarize=true"

echo "Job started, check webhook.site for results"
```
