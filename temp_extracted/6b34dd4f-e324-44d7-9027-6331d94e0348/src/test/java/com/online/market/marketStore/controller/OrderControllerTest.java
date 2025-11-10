package com.online.market.marketStore.controller;

import com.online.market.marketStore.entity.Order;
import com.online.market.marketStore.service.OrderService;
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
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
public class OrderControllerTest {

    @Mock
    private OrderService orderService;

    @InjectMocks
    private OrderController orderController;

    @BeforeEach
    void setUp() {
        Mockito.reset(orderService);
    }

    @Test
    public void testGetOrderById_HappyPath_ReturnsOrder() {
        // Arrange
        Long orderId = 1L;
        Optional<Order> expectedOrder = Optional.of(new Order());
        when(orderService.findOrderById(orderId)).thenReturn(expectedOrder);

        // Act
        ResponseEntity<Optional<Order>> response = orderController.getOrderById(orderId);

        // Assert
        assertEquals(ResponseEntity.ok(expectedOrder), response);
    }

    @Test
    public void testGetOrderById_OrderNotFound_ReturnsEmpty() {
        // Arrange
        Long orderId = 1L;
        Optional<Order> expectedOrder = Optional.empty();
        when(orderService.findOrderById(orderId)).thenReturn(expectedOrder);

        // Act
        ResponseEntity<Optional<Order>> response = orderController.getOrderById(orderId);

        // Assert
        assertEquals(ResponseEntity.ok(expectedOrder), response);
    }

    @Test
    public void testGetAllOrders_HappyPath_ReturnsList() {
        // Arrange
        List<Order> expectedOrderList = List.of(new Order(), new Order());
        when(orderService.findAllOrders()).thenReturn(expectedOrderList);

        // Act
        ResponseEntity<List<Order>> response = orderController.getAllOrders();

        // Assert
        assertEquals(ResponseEntity.ok(expectedOrderList), response);
    }

    @Test
    public void testAddOrder_HappyPath_ReturnsCreatedMessage() {
        // Arrange
        Order expectedOrder = new Order();
        when(orderService.saveOrder(expectedOrder)).thenReturn(expectedOrder);

        // Act
        String response = orderController.addOrder(expectedOrder);

        // Assert
        assertEquals("Created" + expectedOrder, response);
    }

    @Test
    public void testUpdateOrder_HappyPath_ReturnsUpdatedMessage() {
        // Arrange

        // Act
        ResponseEntity<String> response = orderController.updateOrder(1L);

        // Assert
        assertEquals(ResponseEntity.ok("Updated Successfully"), response);
    }

    @Test
    public void testDeleteOrder_HappyPath_ReturnsDeletedMessage() {
        // Arrange

        // Act
        ResponseEntity<String> response = orderController.deleteOrder(1L);

        // Assert
        assertEquals(ResponseEntity.ok("Deleted Successfully"), response);
    }
}