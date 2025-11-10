package com.online.market.marketStore.service;

import com.online.market.marketStore.repository.OrderRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
public class OrderServiceTest {

    @Mock
    private OrderRepository orderRepository;

    @InjectMocks
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        Mockito.reset(orderRepository);
    }

    // Create
    @Test
    public void saveOrder_SavesOrder_ReturnsSavedOrder() {
        // Arrange
        Order order = new Order();
        when(orderRepository.save(order)).thenReturn(order);

        // Act
        Order savedOrder = orderService.saveOrder(order);

        // Assert
        assertEquals(order, savedOrder);
    }

    @Test
    public void saveOrder_NullOrder_ThrowsNullPointerException() {
        // Arrange

        // Act and Assert
        assertThrows(NullPointerException.class, () -> orderService.saveOrder(null));
    }

    // Read All
    @Test
    public void findAllOrders_ReturnsAllOrders() {
        // Arrange
        List<Order> orders = List.of(new Order(), new Order());
        when(orderRepository.findAll()).thenReturn(orders);

        // Act
        List<Order> allOrders = orderService.findAllOrders();

        // Assert
        assertEquals(orders, allOrders);
    }

    @Test
    public void findAllOrders_EmptyList_ReturnsEmptyList() {
        // Arrange
        when(orderRepository.findAll()).thenReturn(List.of());

        // Act
        List<Order> allOrders = orderService.findAllOrders();

        // Assert
        assertNotNull(allOrders);
        assertEquals(0, allOrders.size());
    }

    // Read by ID
    @Test
    public void findOrderById_FoundOrder_ReturnsOptionalWithFoundOrder() {
        // Arrange
        Order order = new Order();
        when(orderRepository.findById(1L)).thenReturn(Optional.of(order));

        // Act
        Optional<Order> foundOrder = orderService.findOrderById(1L);

        // Assert
        assertEquals(Optional.of(order), foundOrder);
    }

    @Test
    public void findOrderById_NotFound_ReturnsEmptyOptional() {
        // Arrange
        when(orderRepository.findById(1L)).thenReturn(Optional.empty());

        // Act
        Optional<Order> foundOrder = orderService.findOrderById(1L);

        // Assert
        assertEquals(Optional.empty(), foundOrder);
    }

    // Update
    @Test
    public void updateOrder_EntityFound_ReturnsUpdatedOrder() {
        // Arrange
        Order order = new Order();
        when(orderRepository.existsById(order.getId())).thenReturn(true);
        when(orderRepository.save(order)).thenReturn(order);

        // Act
        Order updatedOrder = orderService.updateOrder(order);

        // Assert
        assertEquals(order, updatedOrder);
    }

    @Test
    public void updateOrder_EntityNotFound_ThrowsIllegalArgumentException() {
        // Arrange
        Order order = new Order();
        when(orderRepository.existsById(order.getId())).thenReturn(false);

        // Act and Assert
        assertThrows(IllegalArgumentException.class, () -> orderService.updateOrder(order));
    }

    // Delete
    @Test
    public void deleteOrderById_EntityFound_VerifiesDeleteCall() {
        // Arrange
        Long id = 1L;
        when(orderRepository.existsById(id)).thenReturn(true);

        // Act
        orderService.deleteOrderById(id);

        // Assert
        verify(orderRepository).deleteById(id);
    }

    @Test
    public void deleteOrderById_EntityNotFound_VerifiesNoDeleteCall() {
        // Arrange
        Long id = 1L;
        when(orderRepository.existsById(id)).thenReturn(false);

        // Act and Assert
        Mockito.verifyZeroInteractions(orderRepository);
    }
}