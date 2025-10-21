import { useCallback, useRef } from 'react';

/**
 * Managed WebSocket helper for the realtime conversation channel.
 */
export const useConversationSocket = ({ onOpen, onClose, onError, onMessage } = {}) => {
  const socketRef = useRef(null);
  const defaultHandlersRef = useRef({ onOpen, onClose, onError, onMessage });

  defaultHandlersRef.current = { onOpen, onClose, onError, onMessage };

  const assignHandlers = (socket, handlers) => {
    socket.onopen = handlers.onOpen || null;
    socket.onclose = handlers.onClose || null;
    socket.onerror = handlers.onError || null;
    socket.onmessage = handlers.onMessage || null;
  };

  const connect = useCallback((url, handlers = {}) => {
    if (!url) {
      throw new Error('Missing WebSocket URL');
    }

    const socket = new WebSocket(url);
    socket.binaryType = 'arraybuffer';
    const mergedHandlers = {
      ...defaultHandlersRef.current,
      ...handlers,
    };
    assignHandlers(socket, mergedHandlers);

    socketRef.current = socket;
    return socket;
  }, []);

  const send = useCallback((data) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data);
      return true;
    }
    return false;
  }, []);

  const disconnect = useCallback((code = 1000, reason = 'Client closing') => {
    const socket = socketRef.current;
    if (!socket) {
      return;
    }

    try {
      socket.onopen = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      socket.close(code, reason);
    } catch (error) {
      console.warn('WebSocket close failed', error);
    } finally {
      socketRef.current = null;
    }
  }, []);

  const isOpen = useCallback(() => {
    const socket = socketRef.current;
    return Boolean(socket && socket.readyState === WebSocket.OPEN);
  }, []);

  return {
    connect,
    disconnect,
    send,
    socketRef,
    isOpen,
    setHandlers: (handlers) => {
      defaultHandlersRef.current = {
        ...defaultHandlersRef.current,
        ...handlers,
      };
      const socket = socketRef.current;
      if (socket) {
        assignHandlers(socket, defaultHandlersRef.current);
      }
    },
  };
};
