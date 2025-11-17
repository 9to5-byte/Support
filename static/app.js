let selectedProject = null;

// Wait for DOM to be ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing...');

    // Handle project selection
    document.querySelectorAll('.project-card').forEach(card => {
        card.addEventListener('click', function() {
            console.log('Project clicked:', this.dataset.project);
            document.querySelectorAll('.project-card').forEach(c => c.classList.remove('selected'));
            this.classList.add('selected');
            selectedProject = this.dataset.project;
            console.log('Selected project:', selectedProject);
        });
    });

    // Handle Enter key in textarea (Ctrl+Enter or Cmd+Enter to submit)
    const questionInput = document.getElementById('question');
    if (questionInput) {
        questionInput.addEventListener('keydown', function(e) {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                submitQuestion();
            }
        });
    }

    // Add click handler to submit button
    const submitBtn = document.querySelector('.btn-submit');
    if (submitBtn) {
        submitBtn.addEventListener('click', submitQuestion);
        console.log('Submit button handler attached');
    }
});

async function submitQuestion() {
    console.log('submitQuestion called');

    const question = document.getElementById('question').value.trim();
    const resultDiv = document.getElementById('result');
    const loading = document.querySelector('.loading');
    const submitBtn = document.querySelector('.btn-submit');

    console.log('Question:', question);
    console.log('Selected project:', selectedProject);

    // Validation
    if (!selectedProject) {
        alert('Please select a project first!');
        return;
    }

    if (!question) {
        alert('Please enter a question!');
        return;
    }

    // Show loading state
    resultDiv.classList.remove('active');
    loading.classList.add('active');
    submitBtn.disabled = true;

    console.log('Sending request to /ask...');

    try {
        const response = await fetch('/ask', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                project: selectedProject,
                question: question
            })
        });

        const data = await response.json();
        console.log('Response data:', data);

        // Hide loading
        loading.classList.remove('active');
        submitBtn.disabled = false;

        if (data.error) {
            // Show error
            resultDiv.className = 'result error active';
            resultDiv.innerHTML = `
                <h2>Error</h2>
                <p class="answer">${data.error}</p>
            `;
        } else {
            // Show result
            resultDiv.className = 'result active';
            let html = `
                <h2>Answer</h2>
                <div class="answer">${data.answer}</div>
            `;

            if (data.sources && data.sources.length > 0) {
                html += `
                    <div class="sources">
                        <h3>Sources:</h3>
                        ${data.sources.map((url, i) =>
                            `<a href="${url}" target="_blank">${i + 1}. ${url}</a>`
                        ).join('')}
                    </div>
                `;
            }

            resultDiv.innerHTML = html;
        }

        // Scroll to result
        resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    } catch (error) {
        console.error('Error in submitQuestion:', error);
        loading.classList.remove('active');
        submitBtn.disabled = false;
        resultDiv.className = 'result error active';
        resultDiv.innerHTML = `
            <h2>Error</h2>
            <p class="answer">Failed to get answer: ${error.message}</p>
        `;
    }
}

console.log('app.js loaded');
