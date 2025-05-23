document.addEventListener("DOMContentLoaded", function () {
    const syncRequestsDiv = document.getElementById('syncRequests');
    const clientsTableBody = document.getElementById('clientsTableBody');
    const clientForm = document.getElementById('clientForm');
    const addClientBtn = document.getElementById('addClientBtn');

    // Handle adding clients (form submission)
    if (clientForm) {
        clientForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            const clientData = {
                name: document.getElementById('client-name').value,
                hostname: document.getElementById('client-hostname').value,
                username: document.getElementById('client-username').value,
                password: document.getElementById('client-password').value
            };

            const response = await fetch('/create_client', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(clientData)
            });

            const data = await response.json();
            alert('Client created successfully!');
            $('#clientFormModal').modal('hide');  // Close modal
            loadClients();  // Refresh client list
        });
    }

    // Load and display sync requests
    async function loadSyncRequests() {
        const response = await fetch('/get_sync_requests');
        const syncRequests = await response.json();

        syncRequests.forEach(request => {
            const card = document.createElement('div');
            card.classList.add('col-md-4', 'sync-card');

            card.innerHTML = `
                <h5>Request ID: ${request.id}</h5>
                <p>Status: ${request.status}</p>
                <p>Progress: ${request.progress}%</p>
                <p>Sudo Commands Executed: ${request.sudo_commands_executed}/${request.total_sudo_commands}</p>
            `;
            syncRequestsDiv.appendChild(card);
        });
    }

    // Load and display clients in table
    async function loadClients() {
        const response = await fetch('/get_clients');
        const clients = await response.json();
        clientsTableBody.innerHTML = '';

        clients.forEach(client => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${client.name}</td>
                <td>${client.hostname}</td>
                <td>${client.username}</td>
                <td>${client.password}</td>
            `;
            clientsTableBody.appendChild(row);
        });
    }

    // Load sync requests and clients on page load
    if (syncRequestsDiv) {
        loadSyncRequests();
    }

    if (clientsTableBody) {
        loadClients();
    }

    // Show modal when add client button is clicked
    addClientBtn.addEventListener('click', () => {
        $('#clientFormModal').modal('show');
    });
});
