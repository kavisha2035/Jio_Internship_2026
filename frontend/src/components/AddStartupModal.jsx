import React, { useState } from 'react';

export default function AddStartupModal({ isOpen, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [chairs, setChairs] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmedName = name.trim();
    const chairsCount = parseInt(chairs);

    if (!trimmedName) {
      alert('Please enter a startup name.');
      return;
    }
    if (isNaN(chairsCount) || chairsCount <= 0) {
      alert('Please enter a valid number of contracted chairs.');
      return;
    }

    setSubmitting(true);
    fetch('/api/startups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: trimmedName, contracted: chairsCount })
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to register startup');
        return res.json();
      })
      .then((data) => {
        console.log('[AddStartup] Registered:', data);
        setName('');
        setChairs('');
        setSubmitting(false);
        onSuccess();
        onClose();
      })
      .catch((err) => {
        console.error('[AddStartup] Error:', err);
        alert('Error registering startup: ' + err.message);
        setSubmitting(false);
      });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Add New Startup</h3>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label htmlFor="startup-name">Startup Name</label>
              <input
                type="text"
                id="startup-name"
                placeholder="e.g. Startup Gamma"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                disabled={submitting}
              />
            </div>
            <div className="form-group">
              <label htmlFor="startup-chairs">Contracted Chairs Required</label>
              <input
                type="number"
                id="startup-chairs"
                placeholder="e.g. 5"
                min="1"
                value={chairs}
                onChange={(e) => setChairs(e.target.value)}
                required
                disabled={submitting}
              />
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onClose}
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={submitting}
              >
                {submitting ? 'Adding...' : 'Add Startup'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
