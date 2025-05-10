"use client";
import React, { useState, useEffect } from "react";
import { X } from "lucide-react";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

interface AlertInstanceProps {
  id: string;
  type: "error" | "success" | "info" | "upload" | "warning";
  title?: string;
  message: string;
  duration?: number;
  dismissible?: boolean;
  onDismiss: (id: string) => void;
}

const AlertInstance = ({ id, type, title, message, dismissible = true, onDismiss }: AlertInstanceProps) => {
  return (
    <Alert
      className={cn(
        "relative mb-2 max-w-sm shadow-md",
        type === "error" && "border-destructive/50 text-destructive dark:border-destructive [&>svg]:text-destructive",
        type === "upload" && "border-blue-200 bg-blue-50 text-blue-700",
        type === "success" && "border-green-200 bg-green-50 text-green-700",
        type === "info" && "border-gray-200 bg-gray-50 text-gray-700",
        type === "warning" && "border-amber-200 bg-amber-50 text-amber-700"
      )}
    >
      {dismissible && (
        <button
          onClick={() => onDismiss(id)}
          className="absolute right-2 top-2 rounded-full p-1 hover:bg-black/5"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      )}

      {title && <AlertTitle className={dismissible ? "pr-5" : ""}>{title}</AlertTitle>}
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
};

interface AlertSystemProps {
  position?: "top-right" | "bottom-right" | "top-left" | "bottom-left" | "top-center" | "bottom-center";
}

export function AlertSystem({ position = "bottom-right" }: AlertSystemProps) {
  const [alerts, setAlerts] = useState<AlertInstanceProps[]>([]);

  // Custom event handlers for adding and removing alerts
  useEffect(() => {
    const handleAddAlert = (event: Event) => {
      const customEvent = event as CustomEvent<{
        id?: string;
        type: "error" | "success" | "info" | "upload" | "warning";
        title?: string;
        message: string;
        duration?: number;
        dismissible?: boolean;
      }>;
      const alert = customEvent.detail;
      if (alert) {
        const newAlert: AlertInstanceProps = {
          ...alert,
          id: alert.id || Date.now().toString(),
          dismissible: alert.dismissible !== false,
          onDismiss: removeAlert,
        };

        setAlerts(prev => [...prev, newAlert]);

        // Auto-dismiss after duration if specified
        if (alert.duration) {
          setTimeout(() => {
            removeAlert(newAlert.id);
          }, alert.duration);
        }
      }
    };

    const handleRemoveAlert = (event: Event) => {
      const customEvent = event as CustomEvent<{ id: string }>;
      const { id } = customEvent.detail;
      if (id) {
        removeAlert(id);
      }
    };

    window.addEventListener("morphik:alert", handleAddAlert as EventListener);
    window.addEventListener("morphik:alert:remove", handleRemoveAlert as EventListener);

    return () => {
      window.removeEventListener("morphik:alert", handleAddAlert as EventListener);
      window.removeEventListener("morphik:alert:remove", handleRemoveAlert as EventListener);
    };
  }, []);

  const removeAlert = (id: string) => {
    setAlerts(prev => prev.filter(alert => alert.id !== id));
  };

  // Position mapping
  const positionClasses = {
    "top-right": "fixed top-4 right-4 z-50",
    "bottom-right": "fixed bottom-4 right-4 z-50",
    "top-left": "fixed top-4 left-4 z-50",
    "bottom-left": "fixed bottom-4 left-4 z-50",
    "top-center": "fixed top-4 left-1/2 -translate-x-1/2 z-50",
    "bottom-center": "fixed bottom-4 left-1/2 -translate-x-1/2 z-50",
  };

  return (
    <div className={cn("flex flex-col animate-in fade-in", positionClasses[position])}>
      {alerts.map(alert => (
        <AlertInstance key={alert.id} {...alert} onDismiss={removeAlert} />
      ))}
    </div>
  );
}

// Helper function to show alerts programmatically
export const showAlert = (
  message: string,
  options?: {
    type?: "error" | "success" | "info" | "upload" | "warning";
    title?: string;
    duration?: number; // in milliseconds, none means it stays until dismissed
    dismissible?: boolean;
    id?: string;
  }
) => {
  const event = new CustomEvent("morphik:alert", {
    detail: {
      id: options?.id || Date.now().toString(),
      type: options?.type || "info",
      title: options?.title,
      message,
      duration: options?.duration,
      dismissible: options?.dismissible !== false,
    },
  });

  window.dispatchEvent(event);
};

// Upload-specific helper for the upload in-progress alert
export const showUploadAlert = (
  count: number,
  options?: {
    dismissible?: boolean;
    id?: string;
  }
) => {
  showAlert(`Uploading ${count} ${count === 1 ? "file" : "files"}...`, {
    type: "upload",
    dismissible: options?.dismissible === undefined ? false : options.dismissible,
    id: options?.id || "upload-alert",
  });
};

// Helper to remove an alert by ID
export const removeAlert = (id: string) => {
  const event = new CustomEvent("morphik:alert:remove", {
    detail: { id },
  });

  window.dispatchEvent(event);
};
